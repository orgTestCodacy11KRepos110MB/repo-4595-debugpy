import json
import sys
import traceback

from _pydev_bundle.pydev_is_thread_alive import is_thread_alive
from _pydev_imps._pydev_saved_modules import thread
from _pydevd_bundle import pydevd_xml
from _pydevd_bundle.pydevd_comm_constants import (
    CMD_THREAD_CREATE, CMD_THREAD_KILL, CMD_THREAD_SUSPEND, CMD_THREAD_RUN, CMD_GET_VARIABLE,
    CMD_EVALUATE_EXPRESSION, CMD_GET_FRAME, CMD_WRITE_TO_CONSOLE, CMD_GET_COMPLETIONS,
    CMD_LOAD_SOURCE, CMD_SET_NEXT_STATEMENT, CMD_EXIT, CMD_GET_FILE_CONTENTS,
    CMD_EVALUATE_CONSOLE_EXPRESSION, CMD_RUN_CUSTOM_OPERATION,
    CMD_GET_BREAKPOINT_EXCEPTION, CMD_SEND_CURR_EXCEPTION_TRACE,
    CMD_SEND_CURR_EXCEPTION_TRACE_PROCEEDED, CMD_SHOW_CONSOLE, CMD_GET_ARRAY,
    CMD_INPUT_REQUESTED, CMD_GET_DESCRIPTION, CMD_PROCESS_CREATED,
    CMD_SHOW_CYTHON_WARNING, CMD_LOAD_FULL_VALUE, CMD_GET_THREAD_STACK,
    CMD_GET_EXCEPTION_DETAILS, CMD_THREAD_SUSPEND_SINGLE_NOTIFICATION,
    CMD_THREAD_RESUME_SINGLE_NOTIFICATION,
    CMD_GET_NEXT_STATEMENT_TARGETS, CMD_VERSION,
    CMD_RETURN, CMD_SET_PROTOCOL, CMD_ERROR, MAX_IO_MSG_SIZE, VERSION_STRING,
    filesystem_encoding_is_utf8, file_system_encoding)
from _pydevd_bundle.pydevd_constants import (DebugInfoHolder, get_thread_id, IS_IRONPYTHON,
    get_global_debugger, GetGlobalDebugger, set_global_debugger)  # Keep for backward compatibility @UnusedImport
from _pydevd_bundle.pydevd_dont_trace_files import DONT_TRACE, PYDEV_FILE
from _pydevd_bundle.pydevd_net_command import NetCommand
from _pydevd_bundle.pydevd_utils import quote_smart as quote, get_non_pydevd_threads
from pydevd_file_utils import get_abs_path_real_path_and_base_from_frame
import pydevd_file_utils
from pydevd_tracing import get_exception_traceback_str

if IS_IRONPYTHON:

    # redefine `unquote` for IronPython, since we use it only for logging messages, but it leads to SOF with IronPython
    def unquote(s):
        return s

get_file_type = DONT_TRACE.get


#=======================================================================================================================
# NetCommandFactory
#=======================================================================================================================
class NetCommandFactory:

    def _thread_to_xml(self, thread):
        """ thread information as XML """
        name = pydevd_xml.make_valid_xml_value(thread.getName())
        cmdText = '<thread name="%s" id="%s" />' % (quote(name), get_thread_id(thread))
        return cmdText

    def make_error_message(self, seq, text):
        cmd = NetCommand(CMD_ERROR, seq, text)
        if DebugInfoHolder.DEBUG_TRACE_LEVEL > 2:
            sys.stderr.write("Error: %s" % (text,))
        return cmd

    def make_protocol_set_message(self, seq):
        return NetCommand(CMD_SET_PROTOCOL, seq, '')

    def make_thread_created_message(self, thread):
        cmdText = "<xml>" + self._thread_to_xml(thread) + "</xml>"
        return NetCommand(CMD_THREAD_CREATE, 0, cmdText)

    def make_process_created_message(self):
        cmdText = '<process/>'
        return NetCommand(CMD_PROCESS_CREATED, 0, cmdText)

    def make_show_cython_warning_message(self):
        try:
            return NetCommand(CMD_SHOW_CYTHON_WARNING, 0, '')
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_custom_frame_created_message(self, frameId, frameDescription):
        frameDescription = pydevd_xml.make_valid_xml_value(frameDescription)
        cmdText = '<xml><thread name="%s" id="%s"/></xml>' % (frameDescription, frameId)
        return NetCommand(CMD_THREAD_CREATE, 0, cmdText)

    def make_list_threads_message(self, seq):
        """ returns thread listing as XML """
        try:
            threads = get_non_pydevd_threads()
            cmd_text = ["<xml>"]
            append = cmd_text.append
            for thread in threads:
                if is_thread_alive(thread):
                    append(self._thread_to_xml(thread))
            append("</xml>")
            return NetCommand(CMD_RETURN, seq, ''.join(cmd_text))
        except:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_thread_stack_message(self, seq, thread_id, topmost_frame, must_be_suspended=False):
        """
        Returns thread stack as XML.

        :param be_suspended: If True and the thread is not suspended, returns None.
        """
        try:
            # If frame is None, the return is an empty frame list.
            cmd_text = ['<xml><thread id="%s">' % (thread_id,)]

            if topmost_frame is not None:
                try:
                    # Note: if we detect that we're already stopped in a given place within
                    # the debugger, use that stack instead of creating a new one with the
                    # current position (this is needed because when an uncaught exception
                    # is reported for a given frame we are actually stopped in a different
                    # place within the debugger).
                    frame = topmost_frame
                    thread_stack_str = ''
                    while frame is not None:
                        if frame.f_code.co_name == 'do_wait_suspend' and frame.f_code.co_filename.endswith('pydevd.py'):
                            thread_stack_str = frame.f_locals.get('thread_stack_str')
                            break
                        frame = frame.f_back
                    else:
                        # Could not find stack of suspended frame...
                        if must_be_suspended:
                            return None
                    cmd_text.append(thread_stack_str or self.make_thread_stack_str(topmost_frame))
                finally:
                    topmost_frame = None
            cmd_text.append('</thread></xml>')
            return NetCommand(CMD_GET_THREAD_STACK, seq, ''.join(cmd_text))
        except:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_variable_changed_message(self, seq, payload):
        # notify debugger that value was changed successfully
        return NetCommand(CMD_RETURN, seq, payload)

    def make_io_message(self, v, ctx):
        '''
        @param v: the message to pass to the debug server
        @param ctx: 1 for stdio 2 for stderr
        '''

        try:
            if len(v) > MAX_IO_MSG_SIZE:
                v = v[0:MAX_IO_MSG_SIZE]
                v += '...'

            v = pydevd_xml.make_valid_xml_value(quote(v, '/>_= '))
            return NetCommand(str(CMD_WRITE_TO_CONSOLE), 0, '<xml><io s="%s" ctx="%s"/></xml>' % (v, ctx))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_version_message(self, seq):
        try:
            return NetCommand(CMD_VERSION, seq, VERSION_STRING)
        except:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_thread_killed_message(self, id):
        try:
            return NetCommand(CMD_THREAD_KILL, 0, str(id))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_thread_stack_str(self, frame, frame_to_lineno=None):
        '''
        :param frame_to_lineno:
            If available, the line number for the frame will be gotten from this dict,
            otherwise frame.f_lineno will be used (needed for unhandled exceptions as
            the place where we report may be different from the place where it's raised).
        '''
        if frame_to_lineno is None:
            frame_to_lineno = {}
        make_valid_xml_value = pydevd_xml.make_valid_xml_value
        cmd_text_list = []
        append = cmd_text_list.append

        curr_frame = frame
        frame = None  # Clear frame reference
        try:
            while curr_frame:
                my_id = id(curr_frame)

                if curr_frame.f_code is None:
                    break  # Iron Python sometimes does not have it!

                method_name = curr_frame.f_code.co_name  # method name (if in method) or ? if global
                if method_name is None:
                    break  # Iron Python sometimes does not have it!

                abs_path_real_path_and_base = get_abs_path_real_path_and_base_from_frame(curr_frame)
                if get_file_type(abs_path_real_path_and_base[2]) == PYDEV_FILE:
                    # Skip pydevd files.
                    curr_frame = curr_frame.f_back
                    continue

                filename_in_utf8 = pydevd_file_utils.norm_file_to_client(abs_path_real_path_and_base[0])
                if not filesystem_encoding_is_utf8 and hasattr(filename_in_utf8, "decode"):
                    # filename_in_utf8 is a byte string encoded using the file system encoding
                    # convert it to utf8
                    filename_in_utf8 = filename_in_utf8.decode(file_system_encoding).encode("utf-8")

                # print("file is ", filename_in_utf8)

                lineno = frame_to_lineno.get(curr_frame, curr_frame.f_lineno)
                # print("line is ", lineno)

                # Note: variables are all gotten 'on-demand'.
                append('<frame id="%s" name="%s" ' % (my_id , make_valid_xml_value(method_name)))
                append('file="%s" line="%s">' % (quote(make_valid_xml_value(filename_in_utf8), '/>_= \t'), lineno))
                append("</frame>")
                curr_frame = curr_frame.f_back
        except:
            traceback.print_exc()

        curr_frame = None  # Clear frame reference
        return ''.join(cmd_text_list)

    def make_thread_suspend_str(
        self,
        thread_id,
        frame,
        stop_reason=None,
        message=None,
        suspend_type="trace",
        frame_to_lineno=None
        ):
        """
        :return tuple(str,str):
            Returns tuple(thread_suspended_str, thread_stack_str).

            i.e.:
            (
                '''
                    <xml>
                        <thread id="id" stop_reason="reason">
                            <frame id="id" name="functionName " file="file" line="line">
                            </frame>
                        </thread>
                    </xml>
                '''
                ,
                '''
                <frame id="id" name="functionName " file="file" line="line">
                </frame>
                '''
            )
        """
        make_valid_xml_value = pydevd_xml.make_valid_xml_value
        cmd_text_list = []
        append = cmd_text_list.append

        cmd_text_list.append('<xml>')
        if message:
            message = make_valid_xml_value(message)

        append('<thread id="%s"' % (thread_id,))
        if stop_reason is not None:
            append(' stop_reason="%s"' % (stop_reason,))
        if message is not None:
            append(' message="%s"' % (message,))
        if suspend_type is not None:
            append(' suspend_type="%s"' % (suspend_type,))
        append('>')
        thread_stack_str = self.make_thread_stack_str(frame, frame_to_lineno)
        append(thread_stack_str)
        append("</thread></xml>")

        return ''.join(cmd_text_list), thread_stack_str

    def make_thread_suspend_message(self, thread_id, frame, stop_reason, message, suspend_type, frame_to_lineno=None):
        try:
            thread_suspend_str, thread_stack_str = self.make_thread_suspend_str(
                thread_id, frame, stop_reason, message, suspend_type, frame_to_lineno=frame_to_lineno)
            cmd = NetCommand(CMD_THREAD_SUSPEND, 0, thread_suspend_str)
            cmd.thread_stack_str = thread_stack_str
            cmd.thread_suspend_str = thread_suspend_str
            return cmd
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_thread_suspend_single_notification(self, thread_id, stop_reason):
        try:
            return NetCommand(CMD_THREAD_SUSPEND_SINGLE_NOTIFICATION, 0, json.dumps(
                {'thread_id': thread_id, 'stop_reason':stop_reason}))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_thread_resume_single_notification(self, thread_id):
        try:
            return NetCommand(CMD_THREAD_RESUME_SINGLE_NOTIFICATION, 0, json.dumps(
                {'thread_id': thread_id}))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_thread_run_message(self, thread_id, reason):
        try:
            return NetCommand(CMD_THREAD_RUN, 0, "%s\t%s" % (thread_id, reason))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_get_variable_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_VARIABLE, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_array_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_ARRAY, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_description_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_DESCRIPTION, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_frame_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_FRAME, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_evaluate_expression_message(self, seq, payload):
        try:
            return NetCommand(CMD_EVALUATE_EXPRESSION, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_completions_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_COMPLETIONS, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_file_contents(self, seq, payload):
        try:
            return NetCommand(CMD_GET_FILE_CONTENTS, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_send_breakpoint_exception_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_BREAKPOINT_EXCEPTION, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def _make_send_curr_exception_trace_str(self, thread_id, exc_type, exc_desc, trace_obj):
        while trace_obj.tb_next is not None:
            trace_obj = trace_obj.tb_next

        exc_type = pydevd_xml.make_valid_xml_value(str(exc_type)).replace('\t', '  ') or 'exception: type unknown'
        exc_desc = pydevd_xml.make_valid_xml_value(str(exc_desc)).replace('\t', '  ') or 'exception: no description'

        thread_suspend_str, thread_stack_str = self.make_thread_suspend_str(
            thread_id, trace_obj.tb_frame, CMD_SEND_CURR_EXCEPTION_TRACE, '')
        return exc_type, exc_desc, thread_suspend_str, thread_stack_str

    def make_send_curr_exception_trace_message(self, seq, thread_id, curr_frame_id, exc_type, exc_desc, trace_obj):
        try:
            exc_type, exc_desc, thread_suspend_str, _thread_stack_str = self._make_send_curr_exception_trace_str(
                thread_id, exc_type, exc_desc, trace_obj)
            payload = str(curr_frame_id) + '\t' + exc_type + "\t" + exc_desc + "\t" + thread_suspend_str
            return NetCommand(CMD_SEND_CURR_EXCEPTION_TRACE, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_get_exception_details_message(self, seq, thread_id, topmost_frame):
        """Returns exception details as XML """
        try:
            # If the debugger is not suspended, just return the thread and its id.
            cmd_text = ['<xml><thread id="%s" ' % (thread_id,)]

            if topmost_frame is not None:
                try:
                    frame = topmost_frame
                    topmost_frame = None
                    while frame is not None:
                        if frame.f_code.co_name == 'do_wait_suspend' and frame.f_code.co_filename.endswith('pydevd.py'):
                            arg = frame.f_locals.get('arg', None)
                            if arg is not None:
                                exc_type, exc_desc, _thread_suspend_str, thread_stack_str = self._make_send_curr_exception_trace_str(
                                    thread_id, *arg)
                                cmd_text.append('exc_type="%s" ' % (exc_type,))
                                cmd_text.append('exc_desc="%s" ' % (exc_desc,))
                                cmd_text.append('>')
                                cmd_text.append(thread_stack_str)
                                break
                        frame = frame.f_back
                    else:
                        cmd_text.append('>')
                finally:
                    frame = None
            cmd_text.append('</thread></xml>')
            return NetCommand(CMD_GET_EXCEPTION_DETAILS, seq, ''.join(cmd_text))
        except:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_send_curr_exception_trace_proceeded_message(self, seq, thread_id):
        try:
            return NetCommand(CMD_SEND_CURR_EXCEPTION_TRACE_PROCEEDED, 0, str(thread_id))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_send_console_message(self, seq, payload):
        try:
            return NetCommand(CMD_EVALUATE_CONSOLE_EXPRESSION, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_custom_operation_message(self, seq, payload):
        try:
            return NetCommand(CMD_RUN_CUSTOM_OPERATION, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_load_source_message(self, seq, source, dbg=None):
        try:
            net = NetCommand(CMD_LOAD_SOURCE, seq, '%s' % source)

        except:
            net = self.make_error_message(0, get_exception_traceback_str())

        if dbg:
            dbg.writer.add_command(net)
        return net

    def make_show_console_message(self, thread_id, frame):
        try:
            thread_suspended_str, _thread_stack_str = self.make_thread_suspend_str(thread_id, frame, CMD_SHOW_CONSOLE, '')
            return NetCommand(CMD_SHOW_CONSOLE, 0, thread_suspended_str)
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_input_requested_message(self, started):
        try:
            return NetCommand(CMD_INPUT_REQUESTED, 0, str(started))
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_set_next_stmnt_status_message(self, seq, is_success, exception_msg):
        try:
            message = str(is_success) + '\t' + exception_msg
            return NetCommand(CMD_SET_NEXT_STATEMENT, int(seq), message)
        except:
            return self.make_error_message(0, get_exception_traceback_str())

    def make_load_full_value_message(self, seq, payload):
        try:
            return NetCommand(CMD_LOAD_FULL_VALUE, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())

    def make_exit_message(self):
        try:
            net = NetCommand(CMD_EXIT, 0, '')

        except:
            net = self.make_error_message(0, get_exception_traceback_str())

        return net

    def make_get_next_statement_targets_message(self, seq, payload):
        try:
            return NetCommand(CMD_GET_NEXT_STATEMENT_TARGETS, seq, payload)
        except Exception:
            return self.make_error_message(seq, get_exception_traceback_str())