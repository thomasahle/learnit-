#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import re, tempfile, subprocess, os, json, textwrap
import itertools, operator, unicodedata
import learnit
from itertools import starmap
from multiprocessing.pool import ThreadPool
from collections import defaultdict

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

def show_sub(sub):
   print(separator_line)
   print('Grade:', learnit.grade_to_name[sub.grade])
   print('Feedback:', sub.feedback)
   print('Last modified:', sub.last_mod)
   print('Submission status:', learnit.substat_to_name[sub.sub_status])
   print('Grading status:', sub.grad_status)
   if sub.comments:
      print('Comments:')
      for comment in sub.comments:
         print('   {fullname} - {time}'.format(**comment))
         nohtml = re.sub(r'<.*?>', '', comment['content'])
         print('   {}'.format(nohtml))

def grade_dialog(client, cid, aid, row):
   sub = client.show_submission(aid, row.row)
   show_sub(sub)
   # Graders
   log = client.get_log(cid, aid)
   graders = [(ga.time, ga.grader) for ga in log if ga.studid in row.studids]
   for time, grader in graders:
      print (time, grader)
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
      'Current feedback: {}\nCurrent grade: {}\n'.format(sub.feedback, learnit.grade_to_name[sub.grade])
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
      er = client.save_grade(aid, row.row, sub.form, abbrv[grade], feedback.strip(), sub.grade_to_code)
      if er == learnit.SUCCESS:
         print('Changes saved')
      else: print('Error')
   else: print('Grading aborted')
   # Clean up
   for f in fs:
      os.unlink(f.name)
   print(separator_line)


class AssignmentDialog(Dialog):
   def __init__(self, client, cid, aid):
      Dialog.__init__(self, aid+'> ')
      self.add_command('([a-zA-Z]{1,2})$', self.grade_cmd, '[group name]', 'Open the grader for a particular group')
      self.add_command('show ([a-zA-Z]{1,2})', self.show_grade_cmd, 'show [group name]', 'Show current grade and feedback for group')
      self.add_command('list$', self.list_cmd, 'list', 'List what groups are available for grading')
      self.add_command('list emails?$', self.list_email_cmd, 'list email', 'List itu email-addresses of groups')
      self.add_command('update$', self.update_cmd, 'update', 'Update table of submissions')
      self.add_command('find (.+)', self.find_group_cmd, 'find [name]', 'Search for groups with a certain member')
      self.client = client
      self.cid = cid
      self.aid = aid

   def run(self):
      print('Loading table...')
      self.subs = client.list_submissions(self.aid)
      print('Found {} groups.'.format(len(self.subs)))
      Dialog.run(self)

   def grade_cmd(self, group):
      group = group.upper()
      if group not in self.subs:
         print('No group with name', group)
         return
      row = self.subs[group]
      if row.substat == learnit.HAS_SUBMIT:
         grade_dialog(self.client, self.cid, self.aid, row)
      else:
         print("Can't grade groups with no submissions.")

   def show_grade_cmd(self, group):
      row = self.subs[group.upper()]
      show_sub(client.show_submission(self.aid, row.row))

   def list_cmd(self):
      groups = sorted((row.substat, row.grade, len(group), group)
         for group, row in self.subs.items())
      for (substat, grade), gs in itertools.groupby(groups, key=operator.itemgetter(0,1)):
         print('{}, {}:'.format(learnit.substat_to_name[substat], learnit.grade_to_name[grade]))
         print('\n'.join(textwrap.wrap(', '.join(map(operator.itemgetter(3), gs)), width=50)))

   def list_email_cmd(self):
      for group, row in sorted(self.subs.items(), key=lambda k_v:(len(k_v[0]),k_v[0])):
         print(group, '; '.join(starmap('{} <{}>'.format, sorted(zip(row.names, row.emails)))))

   def update_cmd(self):
      print('Deleting files named *.cached...')
      for f in os.listdir('.'):
         if os.path.isfile(f) and f.endswith('.cached'):
            os.unlink(f)
      self.run()
      return True

   def find_group_cmd(self, name):
      normal = lambda s: ''.join(c for c in unicodedata.normalize('NFD', s)
            if unicodedata.category(c) != 'Mn').lower().strip()
      for group, row in self.subs.items():
         if any(normal(word).startswith(normal(name))
               for rname in row.names for word in rname.split()):
            print(group, ', '.join(row.names))


class MainDialog(Dialog):
   def __init__(self, client, data):
      Dialog.__init__(self, '> ')
      self.add_command('list assignments|la$', self.list_assignments_cmd, 'list assignments', 'List available assignments from courses')
      self.add_command('(?:grade|g)\s*(\d+)$', self.grade_cmd, 'grade [assignment id]', 'Exit the program')
      self.add_command('table\s*(\d+)$', self.table_cmd, 'table [course id]', 'Print assignment status table for course')
      self.add_command('results?\s*(\d+)$', self.result_cmd, 'result [course id]', 'Number of assignments per group')
      self.add_command('tograde?\s*(\d+)$', self.tograde_cmd, 'tograde [course id]', 'List what tasks are currently ungraded')
      self.client = client
      self.data = data
      self.courses = []
   
   def run(self):
      print("Hello {}!".format(self.client.get_logininfo(self.data)))
      courses = client.list_my_courses(self.data)
      assignments = ThreadPool().map(self.client.list_assignments, courses.keys())
      self.courses = [(cid, cname, list(ass.items()))
         for (cid, cname), ass in zip(courses.items(), assignments)]
      Dialog.run(self)

   def list_assignments_cmd(self):
      for cid, cname, assignments in sorted(self.courses):
         print("{}: {}".format(cid, cname))
         for aid, aname in sorted(assignments):
            print(" "*3 + "{}: {}".format(aid, aname))

   def grade_cmd(self, aid):
      cid = next(cid for cid,_,assignments in self.courses
         if aid in (aid_ for aid_,_ in assignments))
      AssignmentDialog(self.client, cid, aid).run()

   def result_cmd(self, courseid):
      print('Loading tables...')
      aids = sorted(self.client.list_assignments(courseid), key=int)
      subss = ThreadPool().map(client.list_submissions, aids)
      ids = set(groupid for subs in subss for groupid in subs.keys())
      result = defaultdict(list)
      for groupid in ids:
         r = sum(1 for subs in subss if subs[groupid].grade == learnit.APPROVED)
         result[r].append(groupid)
      for (r, groups) in sorted(result.items()):
         print('{} Approves:'.format(r))
         for groupid in groups:
            pend = sum(1 for subs in subss if subs[groupid].substat == learnit.HAS_SUBMIT and subs[groupid].grade == learnit.NO_GRADE)
            noac = sum(1 for subs in subss if subs[groupid].substat == learnit.HAS_SUBMIT and subs[groupid].grade == learnit.NOT_APPROVED)
            nosu = sum(1 for subs in subss if subs[groupid].substat == learnit.NO_SUBMIT)
            tags = ['{} {}'.format(n,s) for n,s in ((pend,'pending'),(noac,'not approved'),(nosu,'not submitted')) if n]
            tagstring = '' if not tags else '({})'.format(', '.join(tags))
            print(groupid+':\t', '; '.join(subss[0][groupid].emails), tagstring)
         print()

   def tograde_cmd(self, courseid):
      print('Loading tables...')
      aids = sorted(self.client.list_assignments(courseid), key=int)
      subss = ThreadPool().map(client.list_submissions, aids)
      for aid, subs in zip(aids, subss):
         groupids = [groupid for groupid, sub in subs.items() if sub.substat == learnit.HAS_SUBMIT and sub.grade == learnit.NO_GRADE]
         if groupids:
            print('Assignment:', aid)
            for groupid in groupids:
               print('Group', groupid)
            print()

   def table_cmd(self, courseid):
      print('Loading tables...')
      aids = sorted(self.client.list_assignments(courseid), key=int)
      subss = ThreadPool().map(client.list_submissions, aids)
      logs = ThreadPool().starmap(client.get_log, ((courseid,aid) for aid in aids))
      cols = [[group for _, group in sorted((len(g),g) for g in subss[0].keys())]]
      for log, subs in zip(logs, subss):
         groups = sorted((len(group), group, row) for group, row in subs.items())
         log = list(log)
         def grader(studids):
            graders = [(ga.time, ga.grader) for ga in log if ga.studid in studids]
            _, grader = sorted(graders, reverse=True)[0] if graders else (0, 'Uknown')
            return grader.split()[-1]
         cols.append([grader(row.studids) for _, _, row in groups])
         def label(substat, grade):
            if substat == learnit.NO_SUBMIT: return '-'
            if substat == learnit.HAS_SUBMIT:
               if grade == learnit.APPROVED: return 'A'
               if grade == learnit.NOT_APPROVED: return 'N'
               if grade == learnit.NO_GRADE: return '.'
            return '?'
         cols.append([label(row.substat, row.grade) for _, _, row in groups])
      rows = [['Group'] + sum(([aid,'-'] for aid in aids),[])] + list(zip(*cols))
      colwidths = [max(len(cell) for cell in col) for col in zip(*rows)]
      for row in rows:
         for i, cell in enumerate(row):
            print(cell.ljust(colwidths[i]), end='\t')
         print()


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
