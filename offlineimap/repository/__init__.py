# Copyright (C) 2002-2007 John Goerzen <jgoerzen@complete.org>
#               2010 Sebastian Spaeth <Sebastian@SSpaeth.de> and contributors
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

from offlineimap.repository.IMAP import IMAPRepository, MappedIMAPRepository
from offlineimap.repository.Gmail import GmailRepository
from offlineimap.repository.Maildir import MaildirRepository
from offlineimap.repository.LocalStatus import LocalStatusRepository
from offlineimap.repository.backup import BackupMaildirRepository

TYPEMAP = {
    ('remote', 'IMAP') : IMAPRepository,
    ('remote', 'Gmail') : IMAPRepository,
    ('local', 'IMAP') : IMAPRepository,
    ('local', 'Maildir') : IMAPRepository,
    ('local', 'Backup') : BackupMaildirRepository,
}

def repository(account, reqtype):
    """Create an initialise a class handling the configured repository type.
    """
    config = account.getconfig()
    if reqtype == 'status':
        name = account.getconf('localrepository')
        return LocalStatusRepository(name, account)

    name = account.getconf(reqtype + 'repository')
    repostype = config.get('Repository ' + name, 'type').strip()

    try:
        repo = TYPEMAP[reqtype, repostype]
    except KeyError:
        raise ValueError("%s %s accounts are not supported." %
                         (reqtype, repostype))

    return repo(name, account)
