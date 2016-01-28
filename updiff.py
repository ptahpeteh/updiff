#!/usr/bin/env python3

# author: Rafał Przywara, (c) 2016
# license: MIT
# usage: updiff.py [-s section] [-d [diff_file]] [-t tag]

import configparser
import subprocess
import posixpath
import argparse
import ftplib
import codecs
import re
import os


# ftp settings file
SETTINGS = 'updiff.ini'
# ignore file list, just like .gitignore
IGNORE = 'updiff.ignore'
# default name of a diff file
DIFF = 'updiff.files'


class Help:
	""" help strings """

	INTRO = \
		'Uploads modified files to an ftp server. The list of the modified files is obtained through ' \
		'git --name-status TAG cmd or from a file given by the cmd line args.'

	EPILOG = \
		'If no section is given [default] is assumed. The settings file {} should specify values for:\n' \
		'  host = address of an ftp server\n' \
		'  user = login user name\n' \
		'  pwd = user password (should be rot13\'ed)\n' \
		'  dir = project directory on the server.'.format(SETTINGS)

	TAG = 'name of the git tag which is the starting point for generating diff list, defaults to HEAD^'

	SECTION = 'name of a section in the {} file defining ftp connection params'.format(SETTINGS)

	DIFF = 'file containing output of the git diff --name-status cmd, defaults to {} if file name omitted'.format(DIFF)


class Settings:
	""" reads ftp settings from ini file and parses cmd line arguments """

	def __init__(self):

		p = argparse.ArgumentParser(description=Help.INTRO, epilog=Help.EPILOG, formatter_class=argparse.RawTextHelpFormatter)

		p.add_argument('-t', '--tag', default='HEAD^', help=Help.TAG)
		p.add_argument('-s', '--section', default='default', help=Help.SECTION)
		p.add_argument('-d', '--diff', nargs='?', default=False, metavar='diff.txt', help=Help.DIFF)

		self._args = p.parse_args()

		c = configparser.ConfigParser()
		c.read(SETTINGS)

		if self._args.section not in c:
			raise ValueError('Missing given section [{}] in the {} file'.format(self._args.section, SETTINGS))

		self._config = c[self._args.section]

	def __getitem__(self, key):
		return self._config[key]

	@property
	def diff(self):
		""" diff file name
		:return: diff file name or None
		"""
		if self._args.diff is None:
			return DIFF

		return self._args.diff

	@property
	def tag(self):
		""" git tag, starting point to diff generation
		:return: git tag
		"""
		return self._args.tag


class Diff:
	""" reads diff from a file or generates it via through """

	_git = ['git', 'diff', '--name-status']

	@staticmethod
	def get(tag, file=None):

		try:
			if file:
				print('Reading diff list from {}...'.format(file), end='')
				with open(file, 'r', encoding='utf-8') as df:
					diffs = df.read()
			else:
				git = Diff._git + [tag]
				print('Generating diff list through {}...'.format(' '.join(git)), end='')
				diffs = subprocess.run(git, stdout=subprocess.PIPE).stdout.decode('utf-8')
		except:
			print('FAILED')
			raise

		print('OK')
		return diffs


class Ftp:
	""" ftp helper """

	def __init__(self, host, user, pwd):
		"""
		:param host: address of the ftp server
		:param user: user name
		:param pwd: password
		"""
		self._host = host
		self._user = user
		self._pwd = pwd

		self._files = []
		self._ignore = [SETTINGS, IGNORE, DIFF]

		self._dir = ''

		self._ftp = None

	def ignore(self, diff_file=None):
		""" parse an ignore file
		:param diff_file: diff file if any to ignore
		"""
		print('Parsing ignore list {}...'.format(IGNORE), end='')

		try:
			if os.path.isfile(IGNORE):
				with open(IGNORE) as file:
					self._ignore = [line.strip() for line in file.readlines()]
			else:
				self._ignore = []

			print('OK, {} file(s) to ignore'.format(len(self._ignore)))

			self._ignore.append(os.path.basename(__file__))
			self._ignore.append(IGNORE)

			if diff_file:
				self._ignore.append(diff_file)

		except:
			print('FAILED')
			raise

	def diff(self, diffs):
		""" parse git diff output
		:param diffs: list of diff files generated with git diff --name-status
		"""
		rx = re.compile('^([a-z])\\s+(\\S+)$', re.I)

		print('Parsing diff list...', end='')

		try:
			for line in diffs.split('\n'):
				m = rx.match(line)
				if m:
					self._files.append((m.group(1), m.group(2)))

			print('OK, {} file(s) to upload'.format(len(self._files)))
			return len(self._files)

		except:
			print('FAILED')
			raise

	def _full_path(self, path):
		""" append given path to project directory on server
		:param path: path to be appended to project dir
		"""
		if path:
			return posixpath.join(self._dir, path)
		else:
			return self._dir

	def connect(self, ftp_dir):
		""" connect to server
		:param ftp_dir: project directory on server
		"""
		self._dir = posixpath.join('/', ftp_dir)
		self._ftp = ftplib.FTP()

		try:
			print('Connecting to {}...'.format(self._host), end='')
			self._ftp.connect(self._host, 21)
			print('OK')

			print(self._ftp.getwelcome())

			print('Logging in user {}...'.format(self._user), end='')
			self._ftp.login(self._user, codecs.decode(self._pwd, 'rot_13'))
			print('OK')

			print('Working dir is {}...'.format(self._dir), end='')
			self._ftp.cwd(self._dir)
			print('OK')

		except:
			print('FAILED')
			raise

	def mkd(self, path):
		""" make directory on server
		:param path: path of dir to create, relative to the project dir
		"""
		fp = self._full_path(path)
		self._ftp.cwd(self._dir)
		pwd = self._ftp.pwd()

		print('Attempt to create {}...'.format(fp), end='')

		try:
			for elem in path.split('/'):

				pwd = posixpath.join(pwd, elem)

				try:
					self._ftp.cwd(elem)
				except Exception as e:
					if str(e.args).count('550'):
						self._ftp.mkd(elem)
						self._ftp.cwd(elem)
						continue

					print('FAILED to cwd to {}'.format(elem))

			print('OK')

		except:
			print('FAILED')
			raise

	def cwd(self, path):
		""" change working directory
		:param path: path to new working directory, relative to project directory
		"""
		fp = self._full_path(path)

		print('Changing working dir to {}...'.format(fp), end='')

		try:
			self._ftp.cwd(fp)
			print('OK')
			return True

		except Exception as e:
			if str(e.args).count('550'):
				print('NOT FOUND')
				return False

			print('FAILED')
			raise

	def delete(self, name):
		""" delete file on server
		:param name: file name relative to project directory
		"""
		fp = posixpath.join(self._ftp.pwd(), name)
		print('Deleting file {}...'.format(fp), end='')

		try:
			self._ftp.delete(name)
			print('OK')

		except Exception as e:
			if str(e.args).count('550'):
				print('NOT FOUND')
				return False

			print('FAILED')
			raise

	def upload(self, path, name):
		""" upload file on server
		:param path: local file path
		:param name: file name on the server (relative to working dir)
		"""
		fp = posixpath.join(self._ftp.pwd(), name)
		print('Uploading file {} => {}...'.format(path, fp), end='')

		try:
			self._ftp.storbinary('STOR ' + name, open(path, 'rb'))
			print('OK')

		except:
			print('FAILED')
			raise

	def process(self):
		""" process previously parsed ignore file and diff list """

		for file in self._files:
			path, name = posixpath.split(file[1])

			print('*** File {}, mode {}...'.format(file[1], file[0]), end='')

			if file[1] in self._ignore:
				print('IGNORING FILE')
				continue

			if posixpath.join(path, '') in self._ignore:
				print('IGNORING DIR')
				continue

			print()

			if not self.cwd(path):
				self.mkd(path)

			fp = self._full_path(path)
			pwd = self._ftp.pwd()

			if fp != pwd:
				print('WORKING DIR DIFFER: {} != {}!'.format(fp, pwd))
				raise RuntimeError()

			if file[0] == 'D':
				self.delete(name)
			else:
				self.upload(file[1], name)

	def disconnect(self):
		""" disconnect from server """
		print('Closing connection...')
		self._ftp.quit()
		self._ftp = None


# main

if __name__ == '__main__':
	config = Settings()

	f = Ftp(config['host'], config['user'], config['pwd'])

	diff = Diff.get(config.tag, config.diff)

	f.diff(diff)
	f.ignore(config.diff)

	f.connect(config['dir'])
	f.process()
	f.disconnect()
