import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode
from html.parser import HTMLParser
from collections import namedtuple
import re, tempfile, subprocess, zipfile, os, io, json, html, textwrap
import itertools, operator, logging

regsafe = lambda s: re.sub(r'([\-\[\]\/\{\}\(\)\*\+\?\.\\\^\$\|])', r'\\\1', s)

open_cmd = "open"
edit_cmd = "vim"
passwd_file = '.password'
course_view = "https://learnit.itu.dk/course/view.php?id="
assign_view = "https://learnit.itu.dk/mod/assign/view.php?id={}&action={}&group={}"
sub_file = "https://learnit.itu.dk/pluginfile.php/{}/assignsubmission_file/submission_files/"
save_grade = "https://learnit.itu.dk/mod/assign/view.php?id={}&rownum={}&action=grade"
page_comment_ajax = "https://learnit.itu.dk/comment/comment_ajax.php"
SUCCESS, INVALID_PASSWORD, UKNOWN_ERROR = range(3)
Submission = namedtuple('Submission', ['form', 'sub_status', 'grad_status', 'last_mod', 'files', 'grade', 'feedback', 'comments', 'context_id'])
accepted_suffices = ['.pdf', '.java', '.zip']
separator_line = '-' * 50

class FormParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.data = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.method = attrs.get('method', 'get').lower()
            self.action = attrs['action']
        if tag == 'input' and 'name' in attrs:
            self.data[attrs['name']] = attrs['value']
def parseForm(data):
    parser = FormParser()
    parser.feed(data)
    return parser

class LoggingOpener:
    def __init__(self, opener):
        self.opener = opener
        self.logger = logging.getLogger('weblogger')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(logging.FileHandler('log'))
    def open(self, url, data=None, binary=False):
        self.logger.debug('Requesting ' + url)
        if data:
            self.logger.debug('Data ' + data.decode('utf-8'))
        resp = self.opener.open(url, data)
        self.logger.debug('Reponse headers: ' + repr(resp.getheaders()))
        payload = resp.read()
        if not binary:
            payload = payload.decode('utf-8')
            self.logger.debug('Response payload: ' + payload)
        else:
            self.logger.debug('Binary response')
        return payload, resp

class Learnit:
    def __init__(self):
        opener = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPHandler(debuglevel=1),
            urllib.request.HTTPSHandler(debuglevel=1),
            urllib.request.HTTPCookieProcessor()
        )
        opener.addheaders = [
            ('User-agent', ('learnit.py'))
        ]
        self.opener = LoggingOpener(opener)

    def login(self, email, password):
        ''' Log in to learnit and return the response for 'learnit.itu.dk/my' '''
        # Step 1, get login form
        _, response = self.opener.open('http://learnit.itu.dk/auth/saml')
        
        # Step 2, submit login form
        query_string = urlparse(response.geturl()).query
        auth_state = parse_qs(query_string)['AuthState'][0]
        login_data = urlencode({
            'RelayState':'',
            'AuthState':auth_state,
            'username':email,
            'password':password,
            'wp-submit':'Login'
        }).encode('utf-8')
        data, _ = self.opener.open('https://wayf.itu.dk/module.php/core/loginuserpass.php?', data=login_data)
        
        # Step 3, send saml to wayf
        if 'Incorrect username or password' in data:
            return None, INVALID_PASSWORD
        parser = FormParser()
        parser.feed(data)
        saml_data = urlencode(parser.data).encode('utf-8')
        assert parser.action == 'https://wayf.wayf.dk/module.php/saml/sp/saml2-acs.php/wayf.wayf.dk'
        assert parser.method == 'post'
        data, _ = self.opener.open(parser.action, data=saml_data)
        
        # Step4, send saml to learnit
        parser = FormParser()
        parser.feed(data)
        saml_data = urlencode(parser.data).encode('utf-8')
        assert parser.action == 'https://learnit.itu.dk/simplesaml/module.php/saml/sp/saml2-acs.php/default-sp'
        assert parser.method == 'post'
        data, response = self.opener.open(parser.action, data=saml_data)
        
        assert response.geturl() == 'https://learnit.itu.dk/my/'
        return data, SUCCESS

    def get_logininfo(self, data):
        regex = '<div class="logininfo">You are logged in as <a.*?>(.*?)</a>'
        return re.search(regex, data).group(1)

    def list_my_courses(self, data):
        regex = r'<a title="([^"]+)" href="{}(\d+)">'.format(regsafe(course_view))
        return {name:title for title,name in re.findall(regex, data)}

    def list_assignments(self, course_id):
        data, _ = self.opener.open('{}{}'.format(course_view, course_id))
        regex = r'<li class="activity assign modtype_assign " id="module-(\d+)">' +\
                r'.*?<span class="instancename">(.*?)</?span'
        return {name:title for name,title in re.findall(regex, data)}

    def list_submissions(self, assign_id):
        cache_name = '.'+assign_id+'.cached'
        if os.path.exists(cache_name):
            with open(cache_name) as f:
                data = f.read()
        else:
            data, _ = self.opener.open(assign_view.format(assign_id, 'grading', '0'))
            with open(cache_name, 'w') as f:
                f.write(data)
        # Todo: 'Default group'
        subs = {}
        for row, dat in re.findall(r'<tr[^<>]+?id="mod_assign_grading_r(\d+)"(.*?)</tr>', data, re.DOTALL):
            match = re.search(r'>Group (.+?)<', dat)
            group = match.group(1) if match else 'Default group'
            match = re.search(r'selected">(.*?)</option>', dat)
            grade = match.group(1) if match else 'No grade'
            match = re.search(r'c6">(.*?)</td>', dat)
            substat = match.group(1) if match else 'Unknown'
            subs[group] = (row, grade, substat)
        return subs

    def download_attachments(self, context_id, filenames):
        clean_name = lambda s: re.sub('[^\w\d\.]', '_', re.sub('\?.*|.*/', '', s))
        for filename in filenames:
            data, _ = self.opener.open(sub_file.format(context_id) + filename, binary=True)
            name = clean_name(filename)
            if name.endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for zname in zf.namelist():
                        if zname.endswith('/'):
                            continue
                        with zf.open(zname) as f:
                            yield (clean_name(zname), f.read())
            else:
                yield (name, data)

    def show_submission(self, assign_id, row):
        data, _ = self.opener.open(save_grade.format(assign_id, row))
        form = parseForm(data)
        match = re.search(r'M\.core_comment\.init\(Y, ({.*?})', data)
        com_json = json.loads(match.group(1) if match else '{}')
        # Comments
        context_id = com_json['contextid']
        match = re.search(r'>Comments \((\d+)\)<', data)
        comments = self.show_comments(form.data['sesskey'], com_json) if match and match.group(1) != '0' else []
        # Status
        match = re.search('>Submission status</td>.+?>(.*?)</td>', data, re.DOTALL)
        sub_status = match.group(1) if match else 'Unknown'
        match = re.search('>Grading status</td>.+?>(.*?)</td>', data, re.DOTALL)
        grad_status = match.group(1) if match else 'Unknown'
        match = re.search('>Last modified</td>.+?>(.*?)</td>', data, re.DOTALL)
        last_mod = match.group(1) if match else 'Unknown'
        # Files
        file_url = regsafe(sub_file.format(context_id))
        files = re.findall(r'href="{}(.*?)"'.format(file_url), data)
        # Grade and feedback
        gradeurl = 'https://learnit.itu.dk/grade/report/grader/index.php'
        match = re.search(r'<a href="{}.*?>(.*?)</a>'.format(regsafe(gradeurl)), data)
        grade = match.group(1) if match else 'Unknown'
        match = re.search(r'<textarea id="id_assignfeedbackcomments_editor.*?>(.*?)</textarea>', data, re.DOTALL)
        feedback = html.unescape(match.group(1) if match else '').replace('<br>','\n')
        return Submission(form, sub_status, grad_status, last_mod, files, grade, feedback, comments, context_id)

    def show_comments(self, sesskey, com_json):
        com_data = urlencode({
            'sesskey': sesskey,
            'action': 'get',
            'client_id': com_json['client_id'],
            'itemid': com_json['itemid'],
            'area': 'submission_comments',
            'courseid': com_json['courseid'],
            'contextid': com_json['contextid'],
            'component': 'assignsubmission_comments',
            'page': '0'
        }).encode('utf-8')
        data, _ = self.opener.open(page_comment_ajax, data=com_data)
        return json.loads(data)['list']

    def save_grade(self, assign_id, row, form, grade, feedback):
        submit_data = urlencode({
            'mform_isexpanded_id_header_comments': '1',
            'mform_isexpanded_id_header_editpdf': '1',
            'id': assign_id,
            'rownum': row,
            'useridlistid': form.data['useridlistid'],
            'attemptnumber': form.data['attemptnumber'],
            'ajax': '0',
            'action': 'submitgrade',
            'sesskey': form.data['sesskey'],
            '_qf__mod_assign_grade_form_'+row: '1',
            'grade': grade,
            'assignfeedbackcomments_editor[text]': feedback.replace('\n','<br>'),
            'assignfeedbackcomments_editor[format]': '1',
            'applytoall': '1',
            'savegrade': 'Save changes'
        }).encode('utf-8')
        data, _ = self.opener.open(form.action, data=submit_data)
        if 'The grade changes were saved' in data:
            return SUCCESS
        return UKNOWN_ERROR

def login_browser(learnit):
    er = INVALID_PASSWORD
    while er != SUCCESS:
        username = input('email: ')
        password = input('password: ')
        print('Logging in...')
        er = learnit.login(username, password)
        if er == INVALID_PASSWORD:
            print("Invalid password!")

def grade_dialog(learnit, assign_id, row):
    sub = learnit.show_submission(assign_id, row)
    print(separator_line)
    print('Grade:', sub.grade)
    print('Feedback:', sub.feedback)
    print('Last modified:', sub.last_mod)
    print('Submission status:', sub.sub_status)
    print('Grading status:', sub.grad_status)
    if sub.comments:
        print('Comments:')
        for comment in sub.comments:
            print('   {fullname} - {time}'.format(**comment))
            nohtml = re.sub(r'<.*?>', '', comment['content'])
            print('   {}'.format(nohtml))
    # Show files
    attachments = list(learnit.download_attachments(sub.context_id, sub.files))
    print('Files:', ', '.join(name for name, _ in attachments))
    feedback = input('Show files? [y/N]: ').lower()
    fs = []
    if feedback == 'y':
        for name, data in attachments:
            if not any(name.endswith(suf) for suf in accepted_suffices):
                print ('Ignoring file: ', name)
                continue
            with tempfile.NamedTemporaryFile(suffix=name, delete=False) as f:
                f.write(data)
                subprocess.call([open_cmd, f.name])
                fs.append(f)
    # Grade
    f = tempfile.NamedTemporaryFile(delete=False)
    edit_message = 'Please enter a feedback message the submission. Lines starting '+\
        'with "#" will be ignored, and an empty message aborts the grading.\n'+\
        'Current feedback: {}\nCurrent grade: {}\n'.format(sub.feedback, sub.grade)
    wrapped = '\n\n'+'\n'.join(line for par in edit_message.splitlines() for line in textwrap.wrap(par, width=60))
    f.write(textwrap.indent(wrapped, '# ').encode('utf-8'))
    f.close()
    subprocess.call([edit_cmd, f.name])
    with open(f.name) as f:
        feedback = ''.join(line for line in f if not re.match('\s*#', line))
    if feedback.strip():
        grade = ''
        abbrv = {'a':'1', 'n':'2', 'o':'-1'}
        while grade not in abbrv:
            grade = input('[A]pproved/[N]ot approved/N[o] grade: ').lower()
        er = learnit.save_grade(assign_id, row, sub.form, abbrv[grade], feedback.strip())
        if er == SUCCESS:
            print('Changes saved')
        else: print('Error')
    else: print('Grading aborted')
    # Clean up
    for f in fs:
        os.unlink(f.name)
    print(separator_line)

def grading_browser(learnit, assign_id):
    print('Loading table...')
    subs = learnit.list_submissions(assign_id)
    print('Found {} groups.'.format(len(subs)))
    while True:
        cmd = input("grade> ").strip()
        if not cmd:
            continue
        if cmd in ('exit', 'quit', 'done'):
            break
        if cmd.upper() in subs:
            row, _, substat = subs[cmd.upper()]
            if substat == 'No submission':
                print("Can't grade group with no submission")
            else:
                grade_dialog(learnit, assign_id, row)
            continue
        if cmd == 'list':
            groups = sorted((substat, grade, len(group), group)
                for group, (_, grade, substat) in subs.items())
            for (substat, grade), gs in itertools.groupby(groups, key=operator.itemgetter(0,1)):
                print('{}, {}:'.format(substat, grade))
                print(', '.join(map(operator.itemgetter(3), gs)))
            continue
        if cmd == 'update':
            for f in os.listdir('.'):
                if os.path.isfile(f) and f.endswith('.cached'):
                    os.unlink(f)
            grading_browser(learnit, assign_id)
            break
        if cmd == 'help':
            print('Supported commands:')
            print('   list         - List what groups are available for grading')
            print('   [group_name] - Open the grader for a particular group')
            print('   update       - Update the table used for `list`')
            print('   exit         - Return to the main menu')
            continue
        print("Unknown command {}".format(repr(cmd)))

def cmd_browser(learnit, data):
    print("Hello {}!".format(learnit.get_logininfo(data)))
    while True:
        line = input("> ").strip()
        if not line:
            continue
        cmd, *args = line.split(' ')
        if cmd == 'help':
            print('Supported commands:')
            print('   list courses                 - List available courses')
            print('   list assignments [course_id] - List available assignments')
            print('   grade [assignment_id]        - Open the grading menu')
            print('   exit                         - Exit the program')
            continue
        if cmd == 'list':
            def show_list(id_name, indent=0):
                for x_id, x_name in sorted(id_name.items()):
                    print(" "*indent + "{}: {}".format(x_id, x_name))
            if args and args[0] == 'courses':
                show_list(learnit.list_my_courses(data))
                continue
            if len(args) == 1 and args[0] == 'assignments':
                for course_id, course_name in sorted(learnit.list_my_courses(data).items()):
                    print("{}: {}".format(course_id, course_name))
                    show_list(learnit.list_assignments(course_id), indent=3)
                continue
            if len(args) == 2 and args[0] == 'assignments' and args[1].isdigit():
                show_list(learnit.list_assignments(args[1]))
                continue
        if cmd == 'grade':
            if len(args) == 1 and args[0].isdigit():
                grading_browser(learnit, args[0])
                continue
        if cmd in ('quit', 'exit', 'done'):
            break
        print("Unknown command {} {}".format(repr(cmd), repr(args)))

if __name__ == '__main__':
    learnit = Learnit()
    if os.path.exists(passwd_file):
        with open(passwd_file) as f:
            passwd = json.loads(f.read())
        data, er = learnit.login(passwd['username'], passwd['password'])
    else:
        data = login_browser(learnit)
    cmd_browser(learnit, data)
