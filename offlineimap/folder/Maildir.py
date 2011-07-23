# Maildir folder support
# Copyright (C) 2002 - 2007 John Goerzen
# <jgoerzen@complete.org>
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

import socket
import time
import re
import os
from Base import BaseFolder
from threading import Lock

try:
    from hashlib import md5
except ImportError:
    from md5 import md5

from offlineimap import OfflineImapError

uidmatchre = re.compile(',U=(\d+)')
flagmatchre = re.compile(':.*2,([A-Z]+)')
timestampmatchre = re.compile('(\d+)');

timeseq = 0
lasttime = long(0)
timelock = Lock()

def gettimeseq():
    global lasttime, timeseq, timelock
    timelock.acquire()
    try:
        thistime = long(time.time())
        if thistime == lasttime:
            timeseq += 1
            return (thistime, timeseq)
        else:
            lasttime = thistime
            timeseq = 0
            return (thistime, timeseq)
    finally:
        timelock.release()

class MaildirFolder(BaseFolder):
    def __init__(self, root, name, sep, repository, accountname, config):
        self.name = name
        self.config = config
        self.dofsync = config.getdefaultboolean("general", "fsync", True)
        self.root = root
        self.sep = sep
        self.messagelist = None
        self.repository = repository
        self.accountname = accountname
        BaseFolder.__init__(self)
        #self.ui is set in BaseFolder.init()
        # Cache the full folder path, as we use getfullname() very often
        self._fullname = os.path.join(self.getroot(), self.getname())

    def getaccountname(self):
        return self.accountname

    def getfullname(self):
        """Return the absolute file path to the Maildir folder (sans cur|new)"""
        return self._fullname

    def getuidvalidity(self):
        """Maildirs have no notion of uidvalidity, so we just return a magic
        token."""
        return 42

    #Checks to see if the given message is within the maximum age according
    #to the maildir name which should begin with a timestamp
    def _iswithinmaxage(self, messagename, maxage):
        #In order to have the same behaviour as SINCE in an IMAP search
        #we must convert this to the oldest time and then strip off hrs/mins
        #from that day
        oldest_time_utc = time.time() - (60*60*24*maxage)
        oldest_time_struct = time.gmtime(oldest_time_utc)
        oldest_time_today_seconds = ((oldest_time_struct[3] * 3600) \
            + (oldest_time_struct[4] * 60) \
            + oldest_time_struct[5])
        oldest_time_utc -= oldest_time_today_seconds

        timestampmatch = timestampmatchre.search(messagename)
        timestampstr = timestampmatch.group()
        timestamplong = long(timestampstr)
        if(timestamplong < oldest_time_utc):
            return False
        else:
            return True


    def _scanfolder(self):
        """Cache the message list.  Maildir flags are:
        R (replied)
        S (seen)
        T (trashed)
        D (draft)
        F (flagged)
        and must occur in ASCII order."""
        retval = {}
        files = []
        # Messages without UIDs get negative UID numbers
        nouidcounter = -1
        foldermd5 = md5(self.getvisiblename()).hexdigest()
        folderstr = ',FMD5=' + foldermd5
        for dirannex in ['new', 'cur']:
            fulldirname = os.path.join(self.getfullname(), dirannex)
            files.extend(os.path.join(fulldirname, filename) for
                         filename in os.listdir(fulldirname))
        for file in files:
            messagename = os.path.basename(file)

            #check if there is a parameter for maxage / maxsize - then see if this
            #message should be considered or not
            maxage = self.config.getdefaultint(
                "Account " + self.accountname, "maxage", -1)
            maxsize = self.config.getdefaultint(
                "Account " + self.accountname, "maxsize", -1)

            if(maxage != -1):
                isnewenough = self._iswithinmaxage(messagename, maxage)
                if(isnewenough != True):
                    #this message is older than we should consider....
                    continue

            # Check and see if the message is too big if the maxsize
            # for this account is set
            if(maxsize != -1):
                filesize = os.path.getsize(file)
                if(filesize > maxsize):
                    continue
            
            if folderstr not in messagename:
                # If there is no folder MD5 specified, or if it mismatches,
                # assume it is a foreign (new) message and generate a
                # negative uid for it
                uid = nouidcounter
                nouidcounter -= 1
            else:                       # It comes from our folder.
                uidmatch = uidmatchre.search(messagename)
                uid = None
                if not uidmatch:
                    uid = nouidcounter
                    nouidcounter -= 1
                else:
                    uid = long(uidmatch.group(1))
            flagmatch = flagmatchre.search(messagename)
            flags = []
            if flagmatch:
                flags = [x for x in flagmatch.group(1)]
            flags.sort()
            retval[uid] = {'uid': uid,
                           'flags': flags,
                           'filename': file}
        return retval

    def quickchanged(self, statusfolder):
        """Returns True if the Maildir has changed"""
        self.cachemessagelist()
        # Folder has different uids than statusfolder => TRUE
        if set(self.getmessageuidlist()) != set(
            statusfolder.getmessageuidlist()):
            return True
        # Also check for flag changes, it's quick on a Maildir 
        for (uid, message) in self.getmessagelist().iteritems():
            if message['flags'] != statusfolder.getmessageflags(uid):
                return True
        return False  #Nope, nothing changed

    def cachemessagelist(self):
        if self.messagelist is None:
            self.messagelist = self._scanfolder()
            
    def getmessagelist(self):
        return self.messagelist

    def getmessage(self, uid):
        """Return the content of the message"""
        filename = self.messagelist[uid]['filename']
        filepath = os.path.join(self.getfullname(), filename)
        file = open(filepath, 'rt')
        retval = file.read()
        file.close()
        #TODO: WHY are we replacing \r\n with \n here? And why do we
        #      read it as text?
        return retval.replace("\r\n", "\n")

    def getmessagetime( self, uid ):
        filename = self.messagelist[uid]['filename']
        filepath = os.path.join(self.getfullname(), filename)
        st = os.stat(filepath)
        return st.st_mtime

    def savemessage(self, uid, content, flags, rtime):
        # This function only ever saves to tmp/,
        # but it calls savemessageflags() to actually save to cur/ or new/.
        self.ui.debug('maildir', 'savemessage: called to write with flags %s '
                      'and content %s' % (repr(flags), repr(content)))
        if uid < 0:
            # We cannot assign a new uid.
            return uid
        if uid in self.messagelist:
            # We already have it, just update flags.
            self.savemessageflags(uid, flags)
            return uid

        # Otherwise, save the message in tmp/ and then call savemessageflags()
        # to give it a permanent home.
        tmpdir = os.path.join(self.getfullname(), 'tmp')
        timeval, timeseq = gettimeseq()
        messagename = '%d_%d.%d.%s,U=%d,FMD5=%s' % (
            timeval,
            timeseq,
            os.getpid(),
            socket.gethostname(),
            uid,
            md5(self.getvisiblename()).hexdigest())
        # open file and write it out
        try:
            fd = os.open(os.path.join(tmpdir, messagename),
                           os.O_EXCL|os.O_CREAT|os.O_WRONLY)
        except OSError, e:
            if e.errno == 17: 
                #FILE EXISTS ALREADY
                severity = OfflineImapError.ERROR.MESSAGE
                raise OfflineImapError("Unique filename %s already existing." %\
                                           messagename, severity)
            else:
                raise

        file = os.fdopen(fd, 'wt')
        file.write(content)
        # Make sure the data hits the disk
        file.flush()
        if self.dofsync:
            os.fsync(fd)
        file.close()

        if rtime != None:
            os.utime(os.path.join(tmpdir, messagename), (rtime, rtime))

        self.messagelist[uid] = {'uid': uid, 'flags': [],
                                 'filename': os.path.join('tmp', messagename)}
        # savemessageflags moves msg to 'cur' or 'new' as appropriate
        self.savemessageflags(uid, flags)
        self.ui.debug('maildir', 'savemessage: returning uid %d' % uid)
        return uid
        
    def getmessageflags(self, uid):
        return self.messagelist[uid]['flags']

    def savemessageflags(self, uid, flags):
        oldfilename = self.messagelist[uid]['filename']
        dir_prefix, newname = os.path.split(oldfilename)
        tmpdir = os.path.join(self.getfullname(), 'tmp')
        if 'S' in flags:
            # If a message has been seen, it goes into the cur
            # directory.  CR debian#152482
            dir_prefix = 'cur'
        else:
            dir_prefix = 'new'
        infostr = ':'
        infomatch = re.search('(:.*)$', newname)
        if infomatch:                   # If the info string is present..
            infostr = infomatch.group(1)
            newname = newname.split(':')[0] # Strip off the info string.
        infostr = re.sub('2,[A-Z]*', '', infostr)
        flags.sort()
        infostr += '2,' + ''.join(flags)
        newname += infostr
        
        newfilename = os.path.join(dir_prefix, newname)
        if (newfilename != oldfilename):
            os.rename(os.path.join(self.getfullname(), oldfilename),
                      os.path.join(self.getfullname(), newfilename))
            self.messagelist[uid]['flags'] = flags
            self.messagelist[uid]['filename'] = newfilename

        # By now, the message had better not be in tmp/ land!
        final_dir, final_name = os.path.split(self.messagelist[uid]['filename'])
        assert final_dir != 'tmp'

    def deletemessage(self, uid):
        """Unlinks a message file from the Maildir.

        :param uid: UID of a mail message
        :type uid: String
        :return: Nothing, or an Exception if UID but no corresponding file
                 found.
        """
        if not self.uidexists(uid):
            return

        filename = self.messagelist[uid]['filename']
        filepath = os.path.join(self.getfullname(), filename)
        try:
            os.unlink(filepath)
        except OSError:
            # Can't find the file -- maybe already deleted?
            newmsglist = self._scanfolder()
            if uid in newmsglist:       # Nope, try new filename.
                filename = newmsglist[uid]['filename']
                filepath = os.path.join(self.getfullname(), filename)
                os.unlink(filepath)
            # Yep -- return.
        del(self.messagelist[uid])
        
