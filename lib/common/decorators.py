"""
MIT License

Copyright (C) 2021 ROCKY4546
https://github.com/rocky4546

This file is part of Cabernet

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the “Software”), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.
"""

import functools
import http
import json
import logging
import os
import re
import socket
import sys
import socket
import time
import urllib
import urllib.error
from functools import update_wrapper

def handle_url_except(f=None, timeout=None):
    """
    timeout not currently used
    """
    if f is None:
        return functools.partial(handle_url_except, timeout=timeout)
    def wrapper_func(self, *args, **kwargs):
        ex_save = None
        i = 2
        while i > 0:
            i -= 1
            try:
                if len(args) > 0:
                    x = str(args[0])
                else:
                    x = 'unknown'
                x = f(self, *args, **kwargs)
                return x
            except UnicodeDecodeError as ex:
                ex_save = ex
                self.logger.info("UnicodeDecodeError in function {}(), retrying {} {} {}" \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0]), ))            
            except urllib.error.HTTPError as ex:
                ex_save = ex
                self.logger.info("HTTPError in function {}(), retrying {} {} {}" \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0]), ))
                # if we get certain codes, it may mean the server is too busy, so slow it down.
                if ex.code == 404:
                    time.sleep(6)
            except urllib.error.URLError as ex:
                ex_save = ex
                self.logger.info("URLError in function {}, retrying (): {} {} {}" \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            except ConnectionResetError as ex:
                ex_save = ex
                self.logger.info("ConnectionResetError in function {}(), retrying {} {} {}" \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            except socket.timeout as ex:
                ex_save = ex
                self.logger.info("Socket Timeout Error in function {}(), retrying {} {} {}" \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            except http.client.RemoteDisconnected as ex:
                ex_save = ex
                self.logger.info('Remote Server Disconnect Error in function {}(), retrying {} {} {}' \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            except http.client.InvalidURL as ex:
                url_tuple = urllib.parse.urlparse(args[0])
                url_list = list(url_tuple)
                url_list[2] = urllib.parse.quote(url_list[2])
                url_list[3] = urllib.parse.quote(url_list[3])
                url_list[4] = urllib.parse.quote(url_list[4])
                url_list[5] = urllib.parse.quote(url_list[5])
                new_url = urllib.parse.urlunparse(url_list)
                args_list = list(args)
                args_list[0] = new_url
                args = tuple(args_list)

                ex_save = ex
                self.logger.info('InvalidURL, encoding and trying again. In function {}() {} {} {}' \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            except http.client.IncompleteRead as ex:
                ex_save = ex
                self.logger.info('Partial data from url received in function {}(), retrying. {} {} {}' \
                    .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
            time.sleep(1.0)
        self.logger.notice('Multiple HTTP Errors, unable to get url data, skipping {}() {} {} {}' \
            .format(f.__qualname__, os.getpid(), str(ex_save), str(args[0])))
        if type(ex_save) == socket.timeout:
            raise ex_save
        
        return None
    return update_wrapper(wrapper_func, f)


def handle_json_except(f):
    def wrapper_func(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except json.JSONDecodeError as jsonError:
            self.logger.error("JSONError in function {}(): {}".format(f.__qualname__, str(jsonError)))
            return None
    return update_wrapper(wrapper_func, f)


class Backup:
    """
    Decorator for collecting and processing export/backup methods
    """
    
    backup2func = {}
    
    def __init__(self, *pattern):
        self.pattern = pattern

    def __call__(self, call_class_fn):
        if call_class_fn is None:
            return call_class_fn
        else:
            for p in self.pattern:
                Backup.backup2func[p] = call_class_fn
            return call_class_fn
            
    @classmethod
    def log_backups(cls):
        logger = logging.getLogger(__name__)
        for name in Backup.backup2func.keys():
            logger.debug('Registering BACKUP {}'.format(name))

    @classmethod
    def call_backup(self, _name, *args, **kwargs):
        """
        Based on function, will create class instance and call
        the function with no parameters. *args are
        passed into the class constructor while **kwargs are
        passed into the instance function
        """
        if _name in Backup.backup2func:
            fn = Backup.backup2func[_name]
            module = fn.__module__
            class_fn = fn.__qualname__
            (cls_name, fn_name) = class_fn.split('.')
            cls = vars(sys.modules[module])[cls_name]
            inst = cls(*args)
            inst_fn = getattr(inst, fn_name)
            inst_fn(**kwargs)
            return True
        else:
            return False


class Restore:
    """
    Decorator for collecting and processing import/restore methods
    """
    
    restore2func = {}
    
    def __init__(self, *pattern):
        self.pattern = pattern

    def __call__(self, call_class_fn):
        if call_class_fn is None:
            return call_class_fn
        else:
            for p in self.pattern:
                Restore.restore2func[p] = call_class_fn
            return call_class_fn
            
    @classmethod
    def log_backups(cls):
        logger = logging.getLogger(__name__)
        for name in Restore.restore2func.keys():
            logger.debug('Registering RESTORE {}'.format(name))

    @classmethod
    def call_restore(cls, _name, *args, **kwargs):
        """
        Based on function, will create class instance and call
        the function with no parameters. *args are
        passed into the class constructor while **kwargs are
        passed into the instance function
        """
        if _name in Restore.restore2func:
            fn = Restore.restore2func[_name]
            module = fn.__module__
            class_fn = fn.__qualname__
            (cls_name, fn_name) = class_fn.split('.')
            cls = vars(sys.modules[module])[cls_name]
            inst = cls(*args)
            inst_fn = getattr(inst, fn_name)
            msg = inst_fn(**kwargs)
            return msg
        else:
            return None


class Request:
    """
    Adds urls to functions for GET and POST methods
    """
    
    def __init__(self):
        self.url2func = {}
        self.method = None

    def route(self, *pattern):
        def wrap(func):
            for p in pattern:
                if p.startswith('RE:'):
                    p = re.compile(p.replace('RE:',''))
                self.url2func[p] = func
            return func
        return wrap

    def log_urls(self):
        logger = logging.getLogger(__name__)
        for name in self.url2func.keys():
            logger.debug('Registering {} URL: {}'.format(self.method, name))

    def call_url(self, _webserver, _name, *args, **kwargs):
        if _name in self.url2func:
            self.url2func[_name](_webserver, *args, **kwargs)
            return True
        else:
            for uri in self.url2func.keys():
                if type(uri) is re.Pattern:
                    if len(uri.findall(_name)) > 0:
                        self.url2func[uri](_webserver, *args, **kwargs)
                        return True
            return False


class GetRequest(Request):

    def __init__(self):
        super().__init__()
        self.method = 'GET'

    
class PostRequest(Request):

    def __init__(self):
        super().__init__()
        self.method = 'POST'


class FileRequest(Request):
    """
    Adds HTDOCS areas to be processed by function
    """

    def __init__(self):
        super().__init__()
        self.method = 'GET'

    def call_url(self, _webserver, _name, *args, **kwargs):
        for key in self.url2func.keys():
            if _name.startswith(key):
                self.url2func[key](_webserver, *args, **kwargs)
                return True
        return False

getrequest = GetRequest()
gettunerrequest = GetRequest()
postrequest = PostRequest()
filerequest = FileRequest()

