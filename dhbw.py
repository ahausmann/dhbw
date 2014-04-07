#!/usr/bin/python

import requests
import argparse
import subprocess
import sys
import stat
import os
import logging
from getpass import getpass
from time import sleep

class Action(object):
    def __init__(self, options):
        self.options = options
        self.logger = logging.getLogger(self.__class__.__name__)

        self.init()

    def init(self):
        pass

    @classmethod
    def setup_parser(self, parser=argparse.ArgumentParser()):
        return parser

    def execute(self):
        pass

    def shutdown(self):
        pass

class Login(Action):
    @classmethod
    def setup_parser(self, parser=argparse.ArgumentParser()):
        # Required parameters
        parser.add_argument("username", help=_("Username to use"))
        # Optional parameters
        parser.add_argument("-p", "--password",
            default=None,
            help=_("Passwort to use. Asks if not given."))
        parser.add_argument("-s", "--server",
            default="zerberus.ba-horb.de",
            help=_("Server to login to."))
        parser.add_argument("-t", "--timeout",
            default=1*60,
            type=float,
            help=_("Timeout in seconds. Defaults to 1 minute."))
        parser.add_argument("--safe-mode",
            help=_("Don't store the password in memory but ask everytime it is needed."))
        return parser

    def init(self):
        self.password = None

    def execute(self):
        self.session = requests.Session()

        self._init_session()

        if not self._login():
            self.logger.error(_("Invalid username/password!"))
            sys.exit(-1)
        else:
            self.logger.info(_("Successfully logged in"))

        while True:
            self.logger.info(_("Sending keep-alive"))
            if not self._keepalive():
                if not self._login():
                    self.logger.error(_("Couldn't log back in"))
                    sys.exit(0)
            else:
                sleep(self.options.timeout)

    def shutdown(self):
        self.logger.info(_("Logging out..."))
        if not self._logout():
            self.logger.error(_("Logout failed"))
        else:
            self.logger.info(_("Goodbye!"))

    def get_passwd(self):
        if self.options.safe_mode:
            return getpass(_("Password: "))
        elif self.password is None:
            self.password = getpass(_("Password: "))
            return self.password
        else:
            return self.password

    def _login(self):
        self.logger.info(_("Logging in..."))
        retries = 5
        response = None

        while retries > 0:
            try:
                response = self.session.post(self._build_url("login-exec.php"), data={"username": self.options.username, "password": self.get_passwd(), "submit": "Log on"}, verify=False)
                break
            except requests.exceptions.ConnectionError:
                self.logger.warn(_("No connection possible... %d retries left", retries))
                sleep(30)
                retries -= 1
        # nicht wieder zurückgeschickt?
        return retries > 0 and not response.url.endswith("index.php")

    def _logout(self):
        response = self.session.get(self._build_url("logout.php"))
        return response.status_code == 200

    def _init_session(self):
        self.logger.info(_("Initializing session..."))
        try:
            response = self.session.get(self._build_url("index.php"), verify=False)
        except requests.exceptions.ConnectionError:
            self.logger.fatal(_("No connection to zerberus possible"))
            sys.exit(1)

        if response.status_code != 200:
            self.logger.fatal(_("No connection to the login server possible"))
            sys.exit(1)

    def _keepalive(self):
        try:
            response = self.session.get(self._build_url("online.php"), verify=False)
            return not response.url.endswith("index.php")
        except requests.exceptions.ConnectionError:
            return False

    def _build_url(self, target):
        return "https://%s/%s" % (self.options.server, target)

class RemoteDesktop(Action):
    def init(self):
        if not check_executable("rdesktop"):
            self.logger.fatal(_("Remote desktop connections require the 'rdesktop' program. Please install it."))

    @classmethod
    def setup_parser(self, parser=argparse.ArgumentParser()):
        parser.add_argument("username", help=_("Username to use."))
        parser.add_argument("--domain", default="ba-horb.de", help=_("Domain to use"))
        parser.add_argument("--server", default="termserv.ba-horb.de", help=_("Terminal server to login into"))
        parser.add_argument("--geometry", default="1024x768", help=_("Display resolution of the remote server"))
        return parser

    def execute(self):
        self.logger.info(_("Connecting to the remote desktop"))
        args = ["rdesktop", "-u", "%s\\%s" % (self.options.domain, self.options.username), "-x", "l", "-a", "16", "-g", self.options.geometry, self.options.server]
        self.logger.debug(" ".join(args))
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.proc.wait()

    def shutdown(self):
        self.proc.poll()
        if self.proc.returncode is None:
            self.logger.info(_("Killing rdesktop process..."))
            self.proc.terminate()

def check_executable(progname):
    for path in os.environ["PATH"].split(":"):
        if os.path.exists("%s/%s" % (path, progname)):
            return True
        # TODO check also for executable rights
    return False

def setup_parser(parser, actioncls):
    parser = actioncls.setup_parser(parser)
    parser.set_defaults(actiontarget=actioncls)
    return parser

def setup_main_parser(parser=argparse.ArgumentParser()):
    parser.add_argument("-v", "--verbose", action="count", default=2)

    parser.add_argument("-f", "--print-format",
        default="{asctime} [{levelname:^8}] >> {message}", help=_("Format to use for logging"))

    subparsers = parser.add_subparsers()

    setup_parser(subparsers.add_parser("login", help=_("Login to Zerberus (internet access within the CampusHorb net)")), Login)
    setup_parser(subparsers.add_parser("termserv", help=_("Establish a connection to the Terminal Server")), RemoteDesktop)

    return parser

def main(args):
    global logger
    parser = setup_main_parser()
    options = parser.parse_args(args)

    logging.basicConfig(format="\r" + options.print_format, style="{", datefmt="%H:%M:%S")

    root_logger = logging.getLogger()
    if options.verbose >= 1:
        root_logger.setLevel(logging.WARNING)
    if options.verbose >= 2:
        root_logger.setLevel(logging.INFO)
    if options.verbose >= 3:
        root_logger.setLevel(logging.DEBUG)
    if options.verbose >= 4:
        root_logger.setLevel(1)
    
    logger = logging.getLogger(__name__)

    if options.actiontarget is None:
        print(_("Please select a subcommand!"))
        sys.exit(1)

    actioncls = options.actiontarget
    action = actioncls(options)
    try:
        action.execute()
    except KeyboardInterrupt:
        logger.info(_("Received keyboard interrupt. Stopping running actions..."))
        action.shutdown()

# BEGIN i18n
def i18nsetup(lang=None, install_as='tr'):
    import bz2, json, builtins, base64, locale
    lang = locale.getlocale()[0] if lang is None else lang
    data = base64.b64decode( \
        "QlpoOTFBWSZTWQtg2LAAA9MfgHDn5RA/718Uv///ulAEGwtJr0DcYowlNIEAmRppqaaNE2qNonqeoaAb" \
        "yiBqeQphIENDQAAABo9QACU9SCBTJpqZMgwQ9RoZBkAyaDmAAmAAJgAAAAANUDJPImj1HqMj1NGgZNGT" \
        "I0aaDTNYGAoiKoqkKqqKIsIh+fgnotOP2kWZIEhQGvwfDATa6RUoium3v6Asyhz9+U6PcKiYqvd9SHa/" \
        "NgwwJpOYa0NqNEPGW2Ryr6btbqWu9Sz461o7Zs7ORTG0xfDNmvdsgRxVfECKTU0UnnIZfmV0ClNizxOy" \
        "0XqGfQ+gbGspQ6CK3ELEKzm2q1aTk0djoObV3XiPFIiBxuUJE8d/lII2W107uD3+Glj1D7JKiaM3MlnR" \
        "6JTcYTbqSgOS4Mx5xBtpHHGGe0iI6LsyipCfqYkOpgl0E9TRiEvISLCKorKEqiQMDH73cPGnFt5OE22G" \
        "Skft3QqsztoJH265K0nhVRhexbNN36mMOR/A2wxvk9o9BONh8j2PjGV1c+dfdsVsVLk7unBUKVsgNZEw" \
        "kDrRZS3IcRlggye5Jg8EkO3AHZ3zMhNpit48JxciQ2D7t86ReCHmSNmb6quxWxcqFJ5Z0qh5KYBkxCod" \
        "/N+J9xzaMic+BXpIAzIDjKVjgjQJEur4EIvnDJT2W/cFFvo15oX23HGl56pnQdjsE7+Jp1CrkWCo1u42" \
        "xZIRexhOqyDtxQk2OtydWaSF8VXy12+dObTNXZ+k5PfHffcWKpDNZVlBo9JJzwoBNrP5g0a/lbuYw0Zn" \
        "rTq9MOShUsGpDHvnCuW6tsvORDkPtQs1NQbmHgGJ75TyWz05YRtPyR1vk2abWVhzmQOGB0+FDbg9LuLj" \
        "+qAnoTTLjrTfMbJGvz8nrq57LokLIZRVUNsQlRsoebzm6Szz251J3xOJDXxmViroFwmL3ISrMTVwSiSJ" \
        "II40kCkzcoFoL1KZzF0aEc+YY1xlthCLAr4OQ2jDvK7AyC7dMTDQypk0YYn0G5CN/VlmcB4DCtTk8xyl" \
        "7JPo/u7dIHXBmKux5tDsOxy8tXYu8dTPbvAgQ7VnwWcZsjlaVM0UMYZXESLMvFD1HUjA3ynMPP1n6SmQ" \
        "Bth0HIMc684szRV2Q57LDy146bZuRqPnF7LSGr2E2oKV0VvusBZbTBrbAcWhsw+OYGmOj2itg5Dhwse9" \
        "1VSDi4UqhY3faGex5krN8mbFmsbGJ9PStGqKA1SgBe1tVmNbJ/1b7MxTLdw9z7585Yyx8Mk0IvYGpAan" \
        "jYGZmg2hUwUDc4O1wDzrlW+0BatGqT/DD/F3JFOFCQC2DYsA" \
    )
    i18n = json.loads(bz2.decompress(data).decode('utf-8'))
    def tr(msg, *args, **kwargs):
        if lang in i18n and msg in i18n[lang]:
            return i18n[lang][msg] % args
        else:
            return msg % args
    builtins.__dict__[install_as] = tr
# END i18n

if __name__ == '__main__':
    i18nsetup(install_as='_')
    main(sys.argv[1:])
