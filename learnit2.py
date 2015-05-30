import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode
from html.parser import HTMLParser
from collections import namedtuple
import re, zipfile, os, io, json, html, csv
from multiprocessing.pool import ThreadPool
import dateutil.parser
import logging
import pickle

# Types
Tables = namedtuple('Tables', [
   'groups', # [Group]
   'assignments', # [Assignment]
   'teachers', # [Teacher]
   'students', # [Student]
   'submissions', # [Submission]
])
Teacher = namedtuple('Teacher', [
   'person', # Person
   'grade_actions', # [GradeAction]
])
Student = namedtuple('Student', [
   'person', # Person
   'group', # Group
   'submit_actions' # [SubmitAction]
])
Person = namedtuple('Person', [
   'id',
   'name',
   'email',
   'icon',
   'last_access'
])
Course = namedtuple('Course', [
   'id',
   'title'
])
Assignment = namedtuple('Assignment', [
   'id',
   'title',
   'submissions' # [Submission]
])
GradeAction = namedtuple('GradeAction', [
   'time',
   'grade',
   'teacher', # Teacher
   'submission' # Submission
])
SubmitAction = namedtuple('SubmitAction', [
   'time',
   'student', # Student
   'submission' # Submission
])
Group = namedtuple('Group', [
   'name',
   'students', # [Student]
   'submissions' # [Submission]
])
Submission = namedtuple('Submission', [
   'row',
   'group', # Group
   'assignment', # Assignment
   'grade_actions', # [GradeAction]
   'submit_actions', # [SubmitAction]
])
SubmissionFull = namedtuple('SubmissionFull', [
   'submission', # Submission
   'feedback',
   'form',
   'context_id',
   'grade_to_code',
   'attachments', # [Attachment]
   'comments', # [Comment]
])
Attachment = namedtuple('Attachment', [
   'filename',
   'data',
])
Comment = namedtuple('Comment', [
   'id',
   'time',
   'content',
   'person', # Person
])

SUCCESS, INVALID_PASSWORD, UNKNOWN_ERROR, WAYF_REDIRECT = range(4)
NO_GRADE, APPROVED, NOT_APPROVED, NO_SUBMISSION = range(4)
ROLE_STUDENT, ROLE_TEACHER, ROLE_TA, ROLE_ALL = 5, 3, 9, 0
grade_to_name = {NO_GRADE: 'Pending', APPROVED: 'Approved', NOT_APPROVED: 'Not approved', NO_SUBMISSION: 'No submission'}
ITU = 'https://learnit.itu.dk'

class FormParser(HTMLParser):
   def __init__(self):
      HTMLParser.__init__(self, convert_charrefs=True)
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
      return self.__get_profile(data), SUCCESS

   def __get_profile(self, data):
      regex = r'You are logged in as <a href=".*?profile.php\?id=(\d+)".*?>(.*?)</a>'
      pid, name = re.search(regex, data).groups()
      person = Person(pid, name, None, None, None)
      regex = r'<li>\s*<a title=".*?" href=".*?course/view\.php\?id=(\d+)">(.*?)</a>'
      courses = [Course(id=cid, title=title) for cid,title in re.findall(regex, data)]
      return person, courses

   def get_tables(self, cid):
      asss, gros, pers, studs, (gras, subs) = \
            ThreadPool().map(lambda f: f(cid), [
         self.__get_assignment_table,
         self.__get_group_table,
         lambda cid_: self.__get_person_table(cid_, ROLE_ALL),
         lambda cid_: self.__get_person_table(cid_, ROLE_STUDENT),
         self.__get_log_table])
      # Create shallow tables
      default_group = Group('No group', [], [])
      groups = [Group(name, [], [])
         for name, pids in gros if pids] \
         + [default_group]
      persons = [Person(pid, name, email, icon, last_access)
         for pid, icon, name, email, last_access in pers]
      students = [Student(person, group, [])
         for group in groups
         for name, pids in gros if group.name == name
         for person in persons if person.id in pids]
      students += [Student(person, default_group, [])
         for person in persons if not any(
            student.person == person for student in students)
         for pid, _, _, _, _ in studs if pid == person.id]
      teachers = [Teacher(person, [])
         for person in persons if not any(
            student.person == person for student in students)]
      assignments = [Assignment(aid, title, [])
         for aid, title in asss]
      # We need the students sorted by pid to find the submission row
      students.sort()
      submissions = [Submission(row, group, assignment, [], [])
         for group in groups
         for assignment in assignments
         for row in [min(i for i, student in enumerate(students) if student.group == group)]]
      grade_actions = [GradeAction(time, grade, teacher, submission)
         for time, pid0, aid, pid1, grade in gras
         for teacher in teachers if teacher.person.id == pid0
         for submission in submissions if submission.assignment.id == aid
         for student in students if student.person.id == pid1 and student.group == submission.group]
      submit_actions = [SubmitAction(time, student, submission)
         for time, pid0, aid in subs
         for student in students if student.person.id == pid0
         for submission in submissions if submission.assignment.id == aid and student.group == submission.group]
      # Inflate 1-n lists
      for student in students:
         student.group.students.append(student)
      for submission in submissions:
         submission.assignment.submissions.append(submission)
         submission.group.submissions.append(submission)
      for grade_action in grade_actions:
         grade_action.teacher.grade_actions.append(grade_action)
         grade_action.submission.grade_actions.append(grade_action)
      for submit_action in submit_actions:
         submit_action.student.submit_actions.append(submit_action)
         submit_action.submission.submit_actions.append(submit_action)
      return Tables(groups, assignments, teachers, students, submissions)

   def __get_assignment_table(self, cid):
      ''' cid -> [(aid, title)] '''
      data, _ = self.opener.open(ITU+'/course/view.php?id='+cid)
      regex = r'<li class=".*?assign " id="module-(\d+)">.*?<span.*?>(.*?)<'
      return re.findall(regex, data, re.DOTALL)

   def __get_group_table(self, cid):
      ''' cid -> [(group_name, [pid])] '''
      data, _ = self.opener.open(ITU+'/group/overview.php?id='+cid)
      groups = []
      regex = r'<tr.*?<td.*?>(.*?)</td>.*?<td.*?>(.*?)</td>'
      for group_name, students in re.findall(regex, data, re.DOTALL):
         regex = r'<a href=".*?id=(\d+)'
         pids = re.findall(regex, students)
         groups.append((group_name, pids))
      return groups

   def __get_person_table(self, cid, role):
      ''' cid -> [(pid, icon, name, email, last_access)] '''
      data, _ = self.opener.open(ITU+'/user/index.php?mode=1&perpage=1000&roleid={}&id={}'.format(role,cid))
      persons = []
      regex = r'<table class="userinfobox">(.*?)</table>'
      for row in re.findall(regex, data, re.DOTALL):
         try:
            pid = re.search(r'user/view\.php\?id=(\d+)', row).group(1)
            icon = None
            name = re.search(r'<div class="username">(.*?)</div>', row).group(1)
            email = re.search(r'href="mailto:(.*?)"', row).group(1)
            last_access = re.search(r'Last access: ([\w\d\s,:]+)', row).group(1)
            if last_access == 'Never':
               last_access = 0
            else: last_access = dateutil.parser.parse(last_access)
            persons.append((pid, icon, name, email, last_access))
         except AttributeError as err:
            print(row)
            raise
      return persons

   def __get_log_table(self, cid):
      ''' cid -> ([(time, pid0, aid, pid1, grade)], [(time, pid0, aid)])'''
      data, _ = self.opener.open(ITU+'/report/log/index.php?chooselog=1&modaction=-view&logformat=showashtml&perpage=1000000&id='+cid)
      grade_actions = []
      submit_actions = []
      regex = r'<tr class="r[01]".*?>(.*?)</tr>'
      for row in re.findall(regex, data, re.DOTALL):
         try:
            time = re.search(r'cell c0".*?>(.*?)</td>', row).group(1)
            time = dateutil.parser.parse(time)
            pid0 = re.search(r'/user/view.php\?id=(\d+)', row).group(1)
            action = re.search(r'cell c3".*?>.*?<a.*?>(.*?)</a>', row).group(1)
            if action == 'assign grade submission':
               aid = re.search(r'/assign/view.php\?id=(\d+)', row).group(1)
               pid1, grade_str = re.search(r'Grade student: \(id=(\d+), fullname=.+\)\. (.*?)\.', row).groups()
               grade = self.__parse_grade(grade_str)
               grade_actions.append((time, pid0, aid, pid1, grade))
            if action == 'assign submit':
               aid = re.search(r'/assign/view.php\?id=(\d+)', row).group(1)
               submit_actions.append((time, pid0, aid))
               if not ('Submitted for grading' in row or 'Afleveret til' in row):
                  raise AttributeError('Bad status')
         except AttributeError as err:
            print(row)
            raise
      return grade_actions, submit_actions

   def __parse_grade(self, grade_str):
      if 'not approved' in grade_str.lower():
         return NOT_APPROVED
      if 'approved' in grade_str.lower():
         return APPROVED
      if 'no grade' in grade_str.lower() or '-' in grade_str.lower():
         return NO_GRADE
      raise AttributeError('Bad grade '+grade_str)

   def get_submission_full(self, submission):
      data, _ = self.opener.open(save_grade.format(submission.assignment.id, submission.row))
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

   def save_grade(self, submission_full, grade, feedback):
      pass # return error
