# kernel.py
import uasyncio as asyncio
import _thread
import time

TREAD = True

class Kernel:
    def __init__(self):
        self.tasks = []
        print("Kernel initialized")

    def add_task(self, task):
        self.tasks.append(task)
        print(f"Task added: {task.name}")

    def find_task(self, name):
      try:
        return next(x for x in self.tasks  if x.name == name)
      except StopIteration:
        return None

    def find_by_group(self, group):
        return [x for x in self.tasks  if str(x.state.get('group')) == str(group) or x.state.get('name') == group ]

    def start(self):
        print("Starting kernel")
        loop = asyncio.get_event_loop()
        for task in self.tasks:
            #print(f"Scheduling task: {task.name}")
            loop.create_task(task.run())

        if TREAD:
          print("Start Event Loop in thread: NonBlock Repl")
          _thread.stack_size(8192)
          _thread.start_new_thread(loop.run_forever, ())
        else:
          print("Start Event Loop: Block Repl")
          loop.run_forever()



class Service:
    _instances = []
    #ALLOW_ARGS = ['state']
    AW_LEN = 1 # async await length min:1
    state = None
    event_list = None

    def __init__(self, name=None, **kwargs):
#or kwargs.get('name')
        self.state = {}
        self.event_list = []
        self.name = name  or self.__class__.__name__  # it is system name variabel
        if kwargs.get('label'):                      # it is human name/label variable fro use in interface
          self.state['label'] = kwargs.get('label')

        #self.AW_LEN = 1 # async await length
        Service._instances.append(self)

    def __str__(self):
      return self.name

    def set_attr__old2(self, **kwargs):
      # set any attr
      for arg in kwargs:
        if hasattr(self, arg) and (arg in self.ALLOW_ARGS):
          setattr(a , arg, kwargs[arg])

    def subscribe(self, proc):
      self.event_list.append(proc)

    def unsubscribe(self, proc):
      if proc in self.event_list:
        ind = self.event_list.index(proc)
        del self.event_list[ind]

    async def subscribe_handler(self):
        for proc in self.event_list:
          try:
            await proc(self)
          except Exception as e:
            self.unsubscribe(proc)

    # to do self proc
    async def tic(self):
      # to do self proc
      pass

    async def run(self):
        tt = 0
        while True:
            tt = time.time_ns() #/1000_000_000
            #tt = time.time()
            if await self.tic():
              await self.subscribe_handler()
            #tt = time.time_ns()/100000
            await asyncio.sleep(self.AW_LEN) #self.AW_LEN
            #load[0] =  min(1, (load[0] *8 + (time.time_ns()/1000_000 -tt)/1000  ) /9)
            load[0] =  min(0.9999, (load[0] *7 + ((time.time_ns() -tt)/1000_000_000 - self.AW_LEN )/1  ) /8)
            #load[0] =  min(1, (load[0] *6 + (time.time_ns()/1000_000_000 -tt +1)/(2)  ) /7)

    @property
    def status(self):
      return {"name":self.name, "state": self.get_status(), "AW_LEN":self.AW_LEN}

    def get_status(self):
        #return {"state": self.state, "name": self.name}
        return self.state

    @classmethod
    def get_instances(cls):
        return cls._instances


os_kernel = Kernel()
load = [0.2]