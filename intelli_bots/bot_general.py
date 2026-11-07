# script_version: 1.1.1
# Purpose: Provide shared script interfaces, versioned JSON and redacted logging for Python and Bash callers.
# Usage: import BotRuntime, script_interface, OutputArgumentParser; --help documents the internal JSON adapter.
# Output: library
"""Shared Python counterpart to bot_general.inc: logging and script interfaces.

Usage: import BotRuntime, script_interface, add_output_arguments. Direct invocation
supports --help/--version or the internal --emit-json --script PATH [--pretty]
stdin adapter used by bot_json. Imports never emit logs or execute commands.
Output: library; CLI adapter serializes one versioned JSON document on stdout.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import logging
import os
import re
import secrets
import stat
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, TextIO

_JSON_DOCUMENT_WRITTEN = False

_SENSITIVE_NAME = re.compile(
    r"(api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)


class BotRuntime:
    def __init__(self, script_path: Path) -> None:
        self.script_name = script_path.name
        self.run_id = secrets.token_hex(3)
        self.debug_enabled = False
        self.console_quiet = False
        self.action = ""
        self.started_at = 0.0
        self.finished = False
        self.log_file: TextIO | None = None

    @staticmethod
    def _timestamp() -> str:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _redact(field: str) -> str:
        field = field.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")
        name, separator, _value = field.partition("=")
        if separator and _SENSITIVE_NAME.search(name):
            return f"{name}=[REDACTED]"
        return field

    def _log(
        self,
        level: str,
        message: str,
        *fields: str,
        stack_depth: int = 2,
        caller: tuple[str, int] | None = None,
    ) -> None:
        if level == "DEBUG" and not self.debug_enabled:
            return
        frame = inspect.currentframe()
        for _ in range(stack_depth):
            frame = frame.f_back if frame is not None else None
        function = frame.f_code.co_name if frame is not None else "main"
        line = frame.f_lineno if frame is not None else 0
        if caller is not None:
            function=re.sub(r'[^A-Za-z0-9_.<>]','_',str(caller[0]))
            line=int(caller[1])
        safe_fields = " ".join(self._redact(str(field)) for field in fields)
        suffix = f" {safe_fields}" if safe_fields else ""
        # Redact the complete sensitive value, including Bearer prefixes,
        # quoted whitespace and cookie lists; losing trailing context is safer
        # than exposing an unquoted multiword credential.
        message=re.sub(r'(?i)(\b(?:api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)\s*[:=]\s*)[^\r\n]*',r'\1[REDACTED]',str(message))
        message=re.sub(r'(?i)\bBearer\s+[^\s,;]+','Bearer [REDACTED]',message)
        safe_message = (
            message.replace("\r", r"\r")
            .replace("\n", r"\n")
            .replace("\t", r"\t")
        )
        entry = (
            f"{self._timestamp()}:{function}[{line}] [{level}] {self.script_name} "
            f"run={self.run_id} {safe_message}{suffix}"
        )
        args=sys.argv[1:]
        interface_args=args[:args.index('--')] if '--' in args else args
        # Structured callers carry failures in their result; retain file logging
        # without adding a second terminal stream of non-JSON diagnostics.
        if not self.console_quiet and os.environ.get('BOT_STRUCTURED_OUTPUT')!='true' and not any(arg in {'--json','--pretty','--response-only'} for arg in interface_args):
            print(entry, file=sys.stderr)
        if self.log_file is not None:
            print(entry, file=self.log_file, flush=True)

    def debug(self, message: str, *fields: str) -> None:
        self._log("DEBUG", message, *fields)

    def info(self, message: str, *fields: str) -> None:
        self._log("INFO", message, *fields)

    def warning(self, message: str, *fields: str) -> None:
        self._log("WARN", message, *fields)

    def error(self, message: str, *fields: str) -> None:
        self._log("ERROR", message, *fields)

    @staticmethod
    def write_json(payload: Any, *, pretty: bool = False) -> None:
        caller = Path(inspect.currentframe().f_back.f_code.co_filename)
        write_json_document(payload, script_path=caller, pretty=pretty)

    def start(
        self,
        action: str,
        *,
        debug: bool = False,
        log_file: Path | None = None,
    ) -> None:
        self.action = action
        self.debug_enabled = debug
        self.started_at = time.monotonic()
        self.finished = False
        if log_file is not None:
            self.set_log_file(log_file)
        self._log("INFO", "Started", f"action={action}", stack_depth=2)

    def set_log_file(self, path: Path) -> None:
        path = path.expanduser()
        if not path.parent.is_dir():
            raise OSError(f"Log file parent directory does not exist: {path.parent}")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:
                raise ValueError('Log path must be an owned single-link regular file')
            os.fchmod(descriptor,0o600)
            self.log_file=os.fdopen(descriptor,'a',encoding='utf-8')
        except BaseException:
            os.close(descriptor)
            raise
        self.debug("File logging enabled", f"path={path}")

    def finish(self, status: int = 0) -> None:
        self.finished = True
        elapsed_ms = int((time.monotonic() - self.started_at) * 1000)
        self._log(
            "INFO",
            "Completed",
            f"action={self.action}",
            f"exit={status}",
            f"elapsed_ms={elapsed_ms}",
            stack_depth=2,
        )

    def fail(self, message: str, *fields: str, status: int = 1) -> NoReturn:
        self._log("ERROR", message, *fields, stack_depth=2)
        self._report_failure(status)
        raise SystemExit(status)

    def fail_exception(self, error: Exception, *, status: int = 1) -> NoReturn:
        self._log(
            "ERROR",
            str(error),
            f"error_type={type(error).__name__}",
            stack_depth=2,
        )
        if self.debug_enabled:
            args=sys.argv[1:];owned=args[:args.index('--')] if '--' in args else args
            if self.log_file is not None:traceback.print_exc(file=self.log_file)
            if not self.console_quiet and os.environ.get('BOT_STRUCTURED_OUTPUT')!='true' and not any(a in {'--json','--pretty','--response-only'} for a in owned):
                traceback.print_exc(file=sys.stderr)
        self._report_failure(status)
        raise SystemExit(status) from error

    def _report_failure(self, status: int) -> None:
        elapsed_ms = int((time.monotonic() - self.started_at) * 1000)
        self._log(
            "ERROR",
            "Failed",
            f"action={self.action}",
            f"exit={status}",
            f"elapsed_ms={elapsed_ms}",
            stack_depth=3,
        )

    def require_execution(
        self,
        *,
        action: str,
        execute: bool,
        assume_yes: bool,
        details: tuple[str, ...] = (),
    ) -> bool:
        if not execute:
            if assume_yes:
                self.fail("--yes requires --execute", f"action={action}", status=2)
            self.info(
                "Plan only; no state changes performed",
                f"action={action}",
                "execute=false",
                *details,
            )
            return False

        if assume_yes:
            self.debug(
                "Confirmation accepted noninteractively",
                f"action={action}",
                "execute=true",
                "yes=true",
                *details,
            )
            return True

        if not sys.stdin.isatty() or not sys.stderr.isatty():
            self.fail(
                "Interactive confirmation unavailable; rerun with --execute --yes",
                f"action={action}",
                status=2,
            )
        response = input(f"Execute {action}? [y/N] ").strip().lower()
        if response not in {"y", "yes"}:
            self.fail("Execution cancelled", f"action={action}", status=3)
        self.debug("Interactive confirmation accepted", f"action={action}")
        return True


def environment_debug_enabled() -> bool:
    return os.environ.get("BOT_DEBUG", "").lower() == "true"

class RuntimeLoggingHandler(logging.Handler):
    """Bridge existing stdlib logging calls into the one BotRuntime log format."""
    def __init__(self, script_path, *, log_file=None):
        super().__init__()
        self.runtime=BotRuntime(Path(script_path))
        if log_file is not None:self.runtime.set_log_file(Path(log_file))

    def emit(self,record):
        try:
            self.runtime._log(record.levelname,record.getMessage(),stack_depth=1,
                              caller=(record.funcName,record.lineno))
        except Exception as error:
            # logging.Handler.handleError dumps raw record arguments and may
            # expose the very credentials this adapter is meant to redact.
            self.runtime.error('Log record formatting failed','error_type='+type(error).__name__)


def configure_standard_logging(script_path, *, level=logging.INFO, log_file=None):
    """Configure the process root logger through the common adapter; never stdout."""
    logger=logging.getLogger()
    handler=RuntimeLoggingHandler(script_path,log_file=log_file)
    for previous in list(logger.handlers):
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler);logger.setLevel(level)
    return handler


OUTPUT_MODES = frozenset({'test','library','text','json','jsonl','protocol','service','wrapper','artifact'})


def script_metadata(script_path):
    """Read source metadata without running the caller or consulting credentials."""
    path=Path(script_path)
    source=path.read_text(encoding='utf-8')
    versions=re.findall(r'^# script_version: (\d+\.\d+\.\d+)$', source, re.M)
    if len(versions)!=1:
        raise ValueError('Expected exactly one script_version header: '+path.name)
    return {'script':path.name,'script_version':versions[0]}


def result_document(payload, *, script_path=None, metadata=None):
    """Build shared versioned result metadata without writing a protocol stream."""
    if metadata is None:
        if script_path is None:raise ValueError('Result requires a source script or explicit worker metadata')
        metadata=script_metadata(script_path)
    elif (not isinstance(metadata,dict) or set(metadata)!={'script','script_version'}
          or not isinstance(metadata['script'],str) or Path(metadata['script']).name!=metadata['script']
          or not re.fullmatch(r'[A-Za-z0-9_.-]+',metadata['script'])
          or not isinstance(metadata['script_version'],str)
          or not re.fullmatch(r'\d+\.\d+\.\d+',metadata['script_version'])):
        raise ValueError('Invalid embedded-worker result metadata')
    document=dict(payload) if isinstance(payload,dict) else {'result':payload}
    existing=document.get('info',{})
    if not isinstance(existing,dict):raise ValueError('JSON info must be an object')
    document['info']={**existing,**metadata}
    return document


def write_json_document(payload, *, script_path=None, pretty=False, metadata=None):
    """Common serializer for shell adapters and Python command results."""
    global _JSON_DOCUMENT_WRITTEN
    document=result_document(payload,script_path=script_path,metadata=metadata)
    print(json.dumps(document,indent=2 if pretty else None,
                     separators=None if pretty else (',',':'),sort_keys=True,ensure_ascii=False,allow_nan=False))
    _JSON_DOCUMENT_WRITTEN=True


def add_output_arguments(parser):
    """Register the common structured CLI options; pretty implies JSON at emission."""
    parser.add_argument('--json',action='store_true',help='Emit a versioned JSON result; logs use stderr')
    parser.add_argument('--pretty',action='store_true',help='Indent JSON; implies --json and only changes whitespace')
    return parser


def run_cli(main, *, script_path, argv=None, output='json'):
    """Own one structured Python result; reject mixed text and duplicate JSON.

    The callback's stdout/stderr are held until its outcome is known. Unexpected
    text or a post-result exception cannot leak a partial success followed by a
    second document. Protocol/raw wrappers retain their original stream owner.
    """
    import contextlib
    import io
    import subprocess
    import tempfile
    args=list(sys.argv[1:] if argv is None else argv)
    interface_args=args[:args.index('--')] if '--' in args else args
    structured=output in {'json','jsonl'} and any(x in {'--json','--pretty','--response-only'} for x in interface_args)
    captured=tempfile.TemporaryFile(mode='w+',encoding='utf-8',errors='replace') if structured else io.StringIO()
    diagnostics=tempfile.TemporaryFile(mode='w+',encoding='utf-8',errors='replace') if structured else io.StringIO()
    ended=None;saved_fds=[]
    code=0;kind=None;message=None
    if structured:
        sys.stdout.flush();sys.stderr.flush()
        saved_fds=[os.dup(1),os.dup(2)]
        os.dup2(captured.fileno(),1);os.dup2(diagnostics.fileno(),2)
    try:
        with contextlib.redirect_stdout(captured) if structured else contextlib.nullcontext():
            with contextlib.redirect_stderr(diagnostics) if structured else contextlib.nullcontext():
                status=main()
                code=status if isinstance(status,int) else 0
    except SystemExit as error:
        if not structured:raise
        ended=error
        code=error.code if isinstance(error.code,int) else (0 if error.code is None else 1)
    except KeyboardInterrupt:
        code=130;kind='KeyboardInterrupt';message='Interrupted'
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        code=1;kind=type(error).__name__;message='Operation failed'
    except Exception as error:
        if not structured:raise
        code=1;kind=type(error).__name__;message='Unhandled command failure'
    finally:
        if structured:
            try:captured.flush();diagnostics.flush()
            except OSError:
                code=1;kind='OSError';message='Output capture failed'
            os.dup2(saved_fds[0],1);os.dup2(saved_fds[1],2)
            for descriptor in saved_fds:os.close(descriptor)
    if structured:
        documents=[]
        if kind is None:
            try:
                captured.seek(0);raw=captured.read()
                documents=[json.loads(line,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number'))) for line in raw.splitlines() if line.strip()] if output=='jsonl' else [json.loads(raw,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))]
                if not documents or any(not isinstance(value,dict) or ('info' in value and not isinstance(value['info'],dict)) for value in documents):
                    raise ValueError('Invalid structured document shape')
            except (ValueError,TypeError):
                code=code or 1;kind='OutputContractError';message='Command produced an invalid structured result'
        if kind is not None:
            documents=[{'ok':False,'error':message,'error_type':kind,'exit_code':code}]
        captured.close();diagnostics.close()
        for value in documents:
            write_json_document(value,script_path=script_path,pretty='--pretty' in interface_args and output!='jsonl')
        if ended is not None:raise SystemExit(code)
    elif kind is not None:
        BotRuntime(Path(script_path)).error(message,'error_type='+kind)
    return code


class OutputArgumentParser(argparse.ArgumentParser):
    """Argument errors obey the same clean JSON/stderr contract as command results."""
    def __init__(self, *args, script_path=None, **kwargs):
        self.script_path=Path(script_path or sys.argv[0])
        self._interface_argv=list(sys.argv[1:])
        super().__init__(*args, **kwargs)

    def parse_args(self,args=None,namespace=None):
        self._interface_argv=list(sys.argv[1:] if args is None else args)
        return super().parse_args(args,namespace)

    def error(self,message):
        args=self._interface_argv
        interface_args=args[:args.index('--')] if '--' in args else args
        if any(arg in {'--json','--pretty'} for arg in interface_args):
            BotRuntime(self.script_path).error('Invalid command line arguments')
            write_json_document({'ok':False,'error':'Invalid command line arguments'},
                                script_path=self.script_path,pretty='--pretty' in self._interface_argv)
            raise SystemExit(2)
        super().error(message)


def script_interface(script_path, *, purpose, output, argv=None):
    """Early direct-invocation help/version/banner; imported modules remain silent.

    This does not serialize a command's results or pretend that tests need JSON.
    Structured/protocol/wrapper callers own their parser and output framing.
    """
    frame=inspect.currentframe().f_back
    if frame.f_globals.get('__name__')!='__main__':return
    if output not in OUTPUT_MODES:raise ValueError('Unknown output contract: '+str(output))
    if not isinstance(purpose,str) or len(purpose.strip())<15:raise ValueError('A concrete script purpose is required')
    args=list(sys.argv[1:] if argv is None else argv)
    metadata=script_metadata(script_path)
    interface_args=args[:args.index('--')] if '--' in args else args
    if '--version' in interface_args:
        print(metadata['script']+' '+metadata['script_version']);raise SystemExit(0)
    if '--help' in interface_args or '-h' in interface_args:
        print(purpose.strip())
        source=Path(script_path).read_text(encoding='utf-8')
        for line in source.splitlines()[:70]:
            if re.match(r'^# (?:Purpose|Usage|Output|Prerequisites|Failure|Example):',line):print(line[2:])
        doc=frame.f_globals.get('__doc__')
        if doc and doc.strip()!=purpose.strip():print(doc.strip())
        try:
            tree=ast.parse(source)
            options=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument':
                    names=[a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str)]
                    helptext=next((k.value.value for k in node.keywords if k.arg=='help' and isinstance(k.value,ast.Constant) and isinstance(k.value.value,str)),'')
                    if names:options.append('  '+', '.join(names)+('  '+helptext if helptext else ''))
            if options:print('Declared command options:\n'+'\n'.join(dict.fromkeys(options)))
        except SyntaxError:pass
        print('Common options: --help, --version. Output contract: '+output+'.')
        if output in {'json','jsonl'}:print('--json and --pretty are owned by this command; --pretty changes JSON whitespace only.')
        elif output=='wrapper':print('Operation/output options are delegated to the documented backend.')
        else:print('Command-specific options are documented in Usage above; unsupported modes fail before work.')
        raise SystemExit(0)
    if output in {'test','library','text','artifact','protocol','service'} and any(x in {'--json','--pretty'} for x in interface_args):
        write_json_document({'ok':False,'error':'JSON CLI output is not supported by this '+output+' interface','exit_code':2},script_path=script_path,pretty='--pretty' in interface_args)
        raise SystemExit(2)
    if output=='library':
        print(metadata['script']+': import this library; use --help for its API',file=sys.stderr)
        raise SystemExit(2)
    # Machine-readable output carries identity in info; no terminal banner.
    if output in {'json','jsonl'} and any(arg in {'--json','--pretty'} for arg in interface_args):
        def structured_exception(error_type,error,trace):
            if not _JSON_DOCUMENT_WRITTEN:
                code=130 if issubclass(error_type,KeyboardInterrupt) else 1
                write_json_document({'ok':False,'error':'Command initialization failed',
                    'error_type':error_type.__name__,'exit_code':code},metadata=metadata,pretty='--pretty' in interface_args)
        sys.excepthook=structured_exception
    if output not in {'json','jsonl'} and not any(arg in {'--json','--pretty'} for arg in interface_args):
        BotRuntime(Path(script_path)).info(metadata['script']+' script_version='+metadata['script_version'])


def _runtime_main():
    import argparse
    parser=OutputArgumentParser(description=__doc__,script_path=__file__)
    parser.add_argument('--version',action='version',version='bot_general.py 1.1.1')
    parser.add_argument('--emit-json',action='store_true',help='Internal shell stdin JSON serialization adapter')
    parser.add_argument('--script',type=Path,help='Calling source script whose metadata must be retained')
    parser.add_argument('--json',action='store_true',help='Adapter stdout is always JSON')
    parser.add_argument('--pretty',action='store_true',help='Indent JSON without changing values')
    args=parser.parse_args()
    if not args.emit_json or args.script is None:parser.error('--emit-json requires --script PATH')
    try:write_json_document(json.load(sys.stdin),script_path=args.script,pretty=args.pretty)
    except (ValueError,OSError) as error:
        runtime=BotRuntime(Path(__file__));runtime.console_quiet=True
        runtime.error('JSON adapter failed','error_type='+type(error).__name__)
        write_json_document({'error':'Invalid JSON input or script metadata'},script_path=Path(__file__),pretty=args.pretty)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(_runtime_main())
