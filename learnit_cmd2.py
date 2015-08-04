#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import re, tempfile, subprocess, os, json, textwrap
import itertools, operator, unicodedata
import learnit2
import datetime
from itertools import starmap
from multiprocessing.pool import ThreadPool
from collections import defaultdict
import pickle

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
               fun(*match.groups())
               break
         else:
            print('Unknown command', repr(cmd))


class MainDialog(Dialog):
   def __init__(self, client, cid):
      Dialog.__init__(self, '> ')
      self.add_command('list assignments|la$', self.list_assignments_cmd, 'list assignments', 'List available assignments from courses')
      self.add_command('results?$', self.result_cmd, 'result', 'Number of assignments per group')
      self.add_command('status (.+)$', self.status_cmd, 'status [group]', 'What\'s going on for that gorup')
      self.add_command('update$', self.update_cmd, 'update', 'Reloads cached tables')
      self.cid = cid
      self.client = client

   def run(self):
      self.tables = self.__get_tables()
      Dialog.run(self)

   def __get_tables(self):
      print('Loading tables...')
      cache_name = '.{}.cached'.format(self.cid)
      if os.path.exists(cache_name):
         with open(cache_name, 'rb') as f:
            tables = pickle.load(f)
      else:
         tables = self.client.get_tables(self.cid)
         with open(cache_name, 'wb') as f:
            pickle.dump(tables, f)
      return tables

   def update_cmd(self):
      print('Deleting files named *.cached...')
      for f in os.listdir('.'):
         if os.path.isfile(f) and f.endswith('.cached'):
            os.unlink(f)
      self.tables = self.__get_tables()

   def list_assignments_cmd(self):
      for (aid, title) in sorted(self.tables.assignments):
         print("{}: {}".format(aid, title))

   def status_cmd(self, group_str):
      groups = [group for group in self.tables.groups
            if group.name.lower() == group_str.lower()]
      if not groups:
         print('No such group')
         return
      group = groups[0]
      for submission in group.submissions:
         aid, title, _ = submission.assignment
         grade = self.__get_submission_grade(submission)
         print(aid, title, '({})'.format(learnit2.grade_to_name[grade]).lower())

   def __get_submission_grade(self, submission):
      if not submission.submit_actions:
         return learnit2.NO_SUBMISSION
      actions = submission.grade_actions + submission.submit_actions
      default_action = learnit2.GradeAction(datetime.datetime(1,1,1), learnit2.NO_GRADE, None, None)
      last = max(actions + [default_action])
      if actions and type(last) == learnit2.GradeAction:
         return last.grade
      if actions and type(last) == learnit2.SubmitAction:
         return learnit2.NO_GRADE

   def result_cmd(self):
      result = defaultdict(list)
      for group in self.tables.groups:
         grades = list(map(self.__get_submission_grade, group.submissions))
         acc = grades.count(learnit2.APPROVED)
         result[acc].append((group, grades))
      for acc, groups in sorted(result.items()):
         print('{} Approves:'.format(acc))
         for group, grades in groups:
            tags = []
            for grade in (learnit2.NO_GRADE, learnit2.NOT_APPROVED, learnit2.NO_SUBMISSION):
               if grade in grades:
                  tags.append('{} {}'.format(grades.count(grade), learnit2.grade_to_name[grade]))
            tagstring = '' if not tags else '({})'.format(', '.join(tags))
            print(group.name+':\t', '; '.join(s.person.email for s in group.students), tagstring)
         print()


def login_dialog(client):
   er = learnit2.INVALID_PASSWORD
   while er != learnit2.SUCCESS:
      username = input('email: ')
      password = input('password: ')
      print('Logging in...')
      data, er = client.login(username, password)
      if er == learnit2.INVALID_PASSWORD:
         print("Invalid password!")
   return data


if __name__ == '__main__':
   client = learnit2.Learnit()
   if os.path.exists(passwd_file):
      with open(passwd_file) as f:
         passwd = json.loads(f.read())
      data, er = client.login(passwd['username'], passwd['password'])
   else:
      data = login_dialog(client)
   print('Hello', data[0].name)
   MainDialog(client, '3003023').run()
