#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import re, tempfile, subprocess, os, json, textwrap
import itertools, operator
import learnit

regsafe = lambda s: re.sub(r'([\-\[\]\/\{\}\(\)\*\+\?\.\\\^\$\|])', r'\\\1', s)

open_cmd = "open"
edit_cmd = "vim"
passwd_file = '.password'
accepted_suffices = ['.pdf', '.java', '.zip']
separator_line = '-' * 50

class Dialog:

   def __init__(self, prefix):
      self.prefix = prefix
      self.help = []
      self.cmds = []
      self.add_command('help', self.__help, 'help', 'Show this message')
      self.add_command('exit|quit|done', self.__exit, 'exit', 'Exit the program')

   def add_command(self, regex, fun, help_cmd, help_text):
      self.help.append((help_cmd, help_text))
      self.cmds.append((re.compile(regex), fun))

   def __help(self):
      print('Supported commands:')
      col_width = max(len(help_cmd) for help_cmd, _ in self.help)
      for help_cmd, help_text in self.help:
         print('  ', help_cmd.ljust(col_width), '-', help_text)

   def __exit(self):
      return True

   def run(self):
      while True:
         cmd = input(self.prefix).strip()
         if not cmd:
            continue
         for (regex, fun) in self.cmds:
            match = regex.match(cmd)
            if match:
               res = fun(*match.groups())
               if res:
                  return
               break
         else:
            print('Unknown command', repr(cmd))


def grade_dialog(client, assign_id, row):
   sub = client.show_submission(assign_id, row)
   print(separator_line)
   print('Grade:', learnit.grade_to_name[sub.grade])
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
   attachments = list(client.download_attachments(sub.context_id, sub.files))
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
      abbrv = {'a':learnit.APPROVED, 'n':learnit.NOT_APPROVED, 'o':learnit.NO_GRADE}
      while grade not in abbrv:
         grade = input('[A]pproved/[N]ot approved/N[o] grade: ').lower()
      er = client.save_grade(assign_id, row, sub.form, abbrv[grade], feedback.strip(), sub.grade_to_code)
      if er == learnit.SUCCESS:
         print('Changes saved')
      else: print('Error')
   else: print('Grading aborted')
   # Clean up
   for f in fs:
      os.unlink(f.name)
   print(separator_line)


class AssignmentDialog(Dialog):
   def __init__(self, client, aid):
      Dialog.__init__(self, aid+'> ')
      self.add_command('([a-zA-Z]{1,2})$', self.grade_cmd, '[group name]', 'Open the grader for a particular group')
      self.add_command('list$', self.list_cmd, 'list', 'List what groups are available for grading')
      self.add_command('list emails?$', self.list_email_cmd, 'list email', 'List itu email-addresses of groups')
      self.add_command('update$', self.update_cmd, 'update', 'Update table of submissions')
      self.client = client
      self.aid = aid
   
   def run(self):
      print('Loading table...')
      self.subs = client.list_submissions(self.aid)
      print('Found {} groups.'.format(len(self.subs)))
      Dialog.run(self)

   def grade_cmd(self, group):
      row, _, substat, emails = self.subs[group.upper()]
      if substat == learnit.HAS_SUBMIT:
         grade_dialog(self.client, self.aid, row)
      else:
         print("Can't grade groups with no submissions.")

   def list_cmd(self):
      groups = sorted((substat, grade, len(group), group)
         for group, (_, grade, substat, emails) in self.subs.items())
      for (substat, grade), gs in itertools.groupby(groups, key=operator.itemgetter(0,1)):
         print('{}, {}:'.format(learnit.substat_to_name[substat], learnit.grade_to_name[grade]))
         print(', '.join(map(operator.itemgetter(3), gs)))

   def list_email_cmd(self):
      for group, (_, grade, substat, emails) in sorted(self.subs.items()):
         print(group, '; '.join(emails))

   def update_cmd(self):
      print('Deleting files named *.cached...')
      for f in os.listdir('.'):
         if os.path.isfile(f) and f.endswith('.cached'):
            os.unlink(f)
      grading_browser(self.client, self.aid)
      return True


class MainDialog(Dialog):
   def __init__(self, client, data):
      Dialog.__init__(self, '> ')
      self.add_command('list courses$', self.list_courses_cmd, 'list courses', 'List available courses')
      self.add_command('list assignments ?(\d+)?$', self.list_assignments_cmd, 'list assignments [course id]', 'List available assignments')
      self.add_command('grade (\d+)$', self.grade_cmd, 'grade [assignment id]', 'Exit the program')
      self.client = client
      self.data = data
   
   def run(self):
      print("Hello {}!".format(self.client.get_logininfo(self.data)))
      Dialog.run(self)

   def __show_list(self, id_name, indent=0):
      for x_id, x_name in sorted(id_name.items()):
         print(" "*indent + "{}: {}".format(x_id, x_name))

   def list_courses_cmd(self):
      self.__show_list(self.client.list_my_courses(self.data))

   def list_assignments_cmd(self, courseid):
      if courseid is not None:
         self.__show_list(self.client.list_assignments(courseid))
      else:
         for course_id, course_name in sorted(client.list_my_courses(data).items()):
            print("{}: {}".format(course_id, course_name))
            self.__show_list(self.client.list_assignments(course_id), indent=3)

   def grade_cmd(self, aid):
      AssignmentDialog(self.client, aid).run()


def login_dialog(client):
   er = learnit.INVALID_PASSWORD
   while er != learnit.SUCCESS:
      username = input('email: ')
      password = input('password: ')
      print('Logging in...')
      er = client.login(username, password)
      if er == learnit.INVALID_PASSWORD:
         print("Invalid password!")


if __name__ == '__main__':
   client = learnit.Learnit()
   if os.path.exists(passwd_file):
      with open(passwd_file) as f:
         passwd = json.loads(f.read())
      data, er = client.login(passwd['username'], passwd['password'])
   else:
      data = login_dialog(client)
   MainDialog(client, data).run()
