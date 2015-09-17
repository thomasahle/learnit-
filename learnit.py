import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode
from html.parser import HTMLParser
from collections import namedtuple
import re, zipfile, os, io, json, html, csv
import dateutil.parser
import logging

SUCCESS, INVALID_PASSWORD, UNKNOWN_ERROR, WAYF_REDIRECT = range(4)
NO_GRADE, APPROVED, NOT_APPROVED = range(3)
HAS_SUBMIT, NO_SUBMIT, UKNOWN_SUBMIT = range(3)

Submission = namedtuple('Submission',
   ['form', 'sub_status', 'grad_status', 'last_mod',
   'files', 'grade', 'feedback', 'comments', 'context_id',
   'grade_to_code'])
Attachment = namedtuple('Attachment', ['filename', 'data'])
Row = namedtuple('Row', ['row', 'grade','substat', 'emails', 'names', 'studids'])
GradeAction = namedtuple('GradeAction', ['time', 'grader', 'studid'])

regsafe = lambda s: re.sub(r'([\-\[\]\/\{\}\(\)\*\+\?\.\\\^\$\|])', r'\\\1', s)
course_view = "https://learnit.itu.dk/course/view.php?id="
assign_view = "https://learnit.itu.dk/mod/assign/view.php?id={}&action={}&group={}"
sub_file = "https://learnit.itu.dk/pluginfile.php/{}/assignsubmission_file/submission_files/"
save_grade = "https://learnit.itu.dk/mod/assign/view.php?id={}&rownum={}&action=grade"
page_comment_ajax = "https://learnit.itu.dk/comment/comment_ajax.php"
page_log = "https://learnit.itu.dk/report/log/index.php"
name_to_grade = {'no grade': NO_GRADE, '-': NO_GRADE, 'approved': APPROVED, 'not approved': NOT_APPROVED}
name_to_substat = {'nothing has been submitted for this assignment': NO_SUBMIT, 'submitted for grading': HAS_SUBMIT, 'no submission': NO_SUBMIT}
grade_to_name = {NO_GRADE: 'No grade', APPROVED: 'Approved', NOT_APPROVED: 'Not approved'}
substat_to_name = {HAS_SUBMIT: 'Submitted', NO_SUBMIT: 'Not submitted', UKNOWN_SUBMIT: 'Unknown'}

class TableParser(HTMLParser):
   def __init__(self):
      HTMLParser.__init__(self)
      self.tables = []
      self.intd = False
   def handle_starttag(self, tag, attrs):
      if tag == 'table':
         self.tables.append([])
      if tag == 'tr':
         self.tables[-1].append([])
      if tag == 'td':
         self.tables[-1][-1].append([])
         self.intd = True
   def handle_data(self, data):
      if self.intd:
         self.tables[-1][-1][-1].append(data)
   def feed(self, data):
      HTMLParser.feed(self, data)
      return self

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
   def feed(self, data):
      HTMLParser.feed(self, data)
      return self

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
      parser = FormParser().feed(data)
      saml_data = urlencode(parser.data).encode('utf-8')
      assert parser.action == 'https://wayf.wayf.dk/module.php/saml/sp/saml2-acs.php/wayf.wayf.dk'
      assert parser.method == 'post'
      data, _ = self.opener.open(parser.action, data=saml_data)
      
      # Step4, send saml to learnit
      parser = FormParser().feed(data)
      saml_data = urlencode(parser.data).encode('utf-8')
      if parser.action == 'https://wayf.wayf.dk/module.php/consent/getconsent.php':
         return None, WAYF_REDIRECT # Wayf has sent us to the consent page. Not supported yet.
      if parser.action != 'https://learnit.itu.dk/simplesaml/module.php/saml/sp/saml2-acs.php/default-sp':
         print('Got action =', parser.action)
         return None, UNKNOWN_ERROR
      assert parser.method == 'post'
      data, response = self.opener.open(parser.action, data=saml_data)
      
      assert response.geturl() == 'https://learnit.itu.dk/my/'
      assert data is not None
      return data, SUCCESS

   def get_logininfo(self, data):
      regex = '<em><i class="fa fa-user"></i>(.*?)</em>'
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
      ''' Returns a dictionary of group_id -> Row object '''
      cache_name = '.'+assign_id+'.cached'
      if os.path.exists(cache_name):
         with open(cache_name) as f:
            data = f.read()
      else:
         data, _ = self.opener.open(assign_view.format(assign_id, 'grading', '0'))
         with open(cache_name, 'w') as f:
            f.write(data)
      if not 'Group submission status' in data:
         print('Warning: Groups appear to be disabled for assignment ' + assign_id + '. ' +
               'This may cause learnit- to fail.')
      subs = {}
      for row, dat in re.findall(r'<tr[^<>]+?id="mod_assign_grading_r(\d+)"(.*?)</tr>', data, re.DOTALL):
         match = re.search(r'>Group (.+?)<', dat)
         group = match.group(1) if match else 'Default group'
         match = re.search(r'selected">(.*?)</option>', dat)
         grade = name_to_grade[match.group(1).lower()] if match else NO_GRADE
         match = re.search(r'_c6">(.*?)</td>', dat)
         substat = name_to_substat[match.group(1).lower()]
         match = re.search(r'_c3">(.*?)</td>', dat)
         email = match.group(1) if match else 'Unknown'
         match = re.search(r'_c2"><a.*?>(.*?)</a></td>', dat)
         name = match.group(1) if match else 'Unknown'
         match = re.search(r'id="selectuser_(\d+)"', dat)
         studid = match.group(1) if match else 'Unknown'
         if group not in subs:
            subs[group] = Row(row, grade, substat, [email], [name], [studid])
         else:
            subs[group].emails.append(email)
            subs[group].names.append(name)
            subs[group].studids.append(studid)
      return subs

   def show_submission(self, assign_id, row):
      data, _ = self.opener.open(save_grade.format(assign_id, row))
      form = FormParser().feed(data)
      if 'Nothing has been submitted for this assignment' in data:
         return Submission(form, NO_SUBMIT, 'Not graded', 'Unknown', [], NO_GRADE, '', [], None, None)
      match = re.search(r'M\.core_comment\.init\(Y, ({.*?})', data)
      com_json = json.loads(match.group(1))
      # Comments
      context_id = com_json['contextid']
      match = re.search(r'>Comments \((\d+)\)<', data)
      comments = self.__show_comments(form.data['sesskey'], com_json) if match and match.group(1) != '0' else []
      # Status
      match = re.search('>Submission status</td>.+?>(.*?)</td>', data, re.DOTALL)
      sub_status = name_to_substat[match.group(1).lower()]
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
      grade = name_to_grade[match.group(1).lower()]
      match = re.search(r'<textarea id="id_assignfeedbackcomments_editor.*?>(.*?)</textarea>', data, re.DOTALL)
      feedback = html.unescape(match.group(1) if match else '').replace('<br>','\n')
      # Figure out grade_to_code table
      grade_to_code = {}
      select = re.search('<select name="grade".*?</select>', data, re.DOTALL).group(0)
      for code, text in re.findall('<option value="([\-\d]+)".*?>(.+?)</option>', select):
         grade_to_code[name_to_grade[text.lower()]] = code
      return Submission(form, sub_status, grad_status, last_mod, files, grade, feedback, comments, context_id, grade_to_code)

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
                     yield Attachment(clean_name(zname), f.read())
         else:
            yield Attachment(name, data)

   def __show_comments(self, sesskey, com_json):
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

   def save_grade(self, assign_id, row, form, grade, feedback, grade_to_code):
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
         'grade': grade_to_code[grade],
         'assignfeedbackcomments_editor[text]': feedback.replace('\n','<br>'),
         'assignfeedbackcomments_editor[format]': '1',
         'applytoall': '1',
         'savegrade': 'Save changes'
      }).encode('utf-8')
      data, _ = self.opener.open(form.action, data=submit_data)
      if 'The grade changes were saved' in data:
         return SUCCESS
      return UKNOWN_ERROR

   def get_log(self, courseid, assignid):
      get_data = urlencode({
         'chooselog': '1',
         'showusers': '1',
         'showcourses': '0',
         'id': courseid,
         'group': '',
         'user': '',
         'date': '0',
         'modid': assignid,
         'modaction': '-view',
         'logformat': 'downloadascsv'
      })
      data, _ = self.opener.open(page_log + '?' + get_data)
      rows = list(csv.reader(io.StringIO(data), dialect='excel-tab'))
      assert rows[1] == ['Course', 'Time', 'IP address', 'User full name', 'Action', 'Information']
      for _, time, _, grader, action, info in rows[2:]:
         if re.match(r'assign grade submission \(.+\)$', action):
            studid = re.match(r'Grade student: \(id=(\d+), fullname=.+\)\.', info).group(1)
            yield GradeAction(dateutil.parser.parse(time), grader, studid)
