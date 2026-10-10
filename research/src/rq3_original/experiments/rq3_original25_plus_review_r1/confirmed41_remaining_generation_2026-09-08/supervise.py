"""Record real child process start/exit without synthesizing runner outcomes."""
from recovery import *
import argparse
import subprocess

def main():
    p=argparse.ArgumentParser();p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--process',type=Path,required=True)
    a=p.parse_args();a.process.mkdir(parents=True,exist_ok=False)
    command=[sys.executable,'-B',str(HERE/'finish_remaining.py'),'--execute','--approval',str(a.approval),'--output',str(a.output)]
    with (a.process/'STDOUT.txt').open('xb') as out,(a.process/'STDERR.txt').open('xb') as err:
        child=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err)
        launch=dict(pid=child.pid,wrapper_pid=os.getpid(),command=command,started_utc=utc(),
                    execution_head=load(a.approval)['binding']['git_head'],no_resume=True)
        write_once(a.process/'PROCESS_LAUNCH.json',launch)
        print(json.dumps(dict(event='PROCESS_STARTED',pid=child.pid)),flush=True)
        result=child.wait()
    write_once(a.process/'PROCESS_EXIT.json',dict(launch,process_exited=True,returncode=result,ended_utc=utc()))
    print(json.dumps(dict(event='PROCESS_EXITED',returncode=result)),flush=True)
    return result

if __name__=='__main__':raise SystemExit(main())
