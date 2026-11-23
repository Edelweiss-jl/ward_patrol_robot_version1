import argparse
import time
from ward_patrol.runtime.core import Runtime
from ward_patrol.runtime.mqtt import SamplingLink


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--beds',nargs='+',default=['N1-1','S3-2'])
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--output',default='outputs/runs',help='运行记录和床位资料 beds.json 所在目录')
    args=parser.parse_args()
    core=Runtime(output=args.output)
    link=None
    try:
        link=SamplingLink(core)
        for bed in args.beds:
            core.submit(dict(action='create_task',bed=bed))
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            core.advance()
            link.flush()
            if core.tasks and all(t.status=='completed' for t in core.tasks):
                print(core.directory)
                return
            time.sleep(.001)
        raise TimeoutError('tasks did not complete; inspect '+str(core.directory))
    finally:
        if link:
            link.bus.close()
        core.close()

if __name__=='__main__':
    main()
