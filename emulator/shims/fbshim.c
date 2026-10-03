/* freestanding shim: fb ioctls (360x360x32) + EVIOCGNAME=x2000_key; passthrough via raw syscall */
#define __NR_ioctl 4054
#define __NR_open  4005
#define __NR_write 4004
#define __NR_close 4006
#define __NR_read 4003
#define __NR_readlink 4085
#define __NR_nanosleep 4166
#define __NR_getpid 4020
static long sys3(long n,long a,long b,long c){
  register long v0 asm("$2")=n,a0 asm("$4")=a,a1 asm("$5")=b,a2 asm("$6")=c; register long a3 asm("$7");
  asm volatile("syscall":"+r"(v0),"=r"(a3):"r"(a0),"r"(a1),"r"(a2)
    :"memory","$8","$9","$10","$11","$12","$13","$14","$15","$24","$25","hi","lo");
  return a3?-v0:v0; }
static void logmsg(const char*s){int i=0;while(s[i])i++;
  long fd=sys3(__NR_open,(long)"/fbshim.log",0x109/*O_WRONLY|O_CREAT|O_APPEND (MIPS)*/,0644);
  if(fd>=0){sys3(__NR_write,fd,(long)s,i);sys3(__NR_close,fd,0,0);}}
static void wr32(unsigned char*p,int off,unsigned int v){p[off]=v;p[off+1]=v>>8;p[off+2]=v>>16;p[off+3]=v>>24;}
#define W 360
#define H 360
#define VY 1080
#define BPP 32
static int eq(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
static int device_is(int fd,const char*name){
  char path[32]="/proc/self/fd/",digits[12],target[128];int n=0,i=14;
  if(fd<0)return 0;
  do{digits[n++]='0'+fd%10;fd/=10;}while(fd);
  while(n)path[i++]=digits[--n];path[i]=0;
  long len=sys3(__NR_readlink,(long)path,(long)target,127);
  if(len<0)return 0;target[len]=0;return eq(target,name);
}
static int marker_is_one(const char*path){
  char value=0;long f=sys3(__NR_open,(long)path,0,0);
  if(f>=0){sys3(__NR_read,f,(long)&value,1);sys3(__NR_close,f,0,0);}
  return value=='1';
}
/* Optional jack model (JACK=..., emulator/docs/audio.md): '3' 3.5 mm plugged,
   '4' 4.4 mm balanced plugged, 'n' nothing. No marker = the model is off. */
static int jack_state(void){
  char value=0;long f=sys3(__NR_open,(long)"/emu/jack",0,0);
  if(f>=0){sys3(__NR_read,f,(long)&value,1);sys3(__NR_close,f,0,0);}
  return value=='3'||value=='4'||value=='n'?value:0;
}
static int adc_device(int fd){
  return device_is(fd,"/dev/jz_adc_aux_0")||device_is(fd,"/dev/jz_adc_aux_1")||
         device_is(fd,"/dev/jz_adc_aux_2")||device_is(fd,"/dev/jz_adc_aux_3");
}
/* Real evdev blocks while idle; our append-only event0 file returns EOF instead.
   echo_loop_key retries immediately, burning one CPU core. Pace only empty key
   reads, never queued events, touch reads, audio or unrelated files. __read is
   the guest libc's exported alias: keep errno/cancellation semantics intact. */
extern long __read(int,void*,unsigned long);
extern int *__errno_location(void);
long read(int fd,void*data,unsigned long count){
  /* Reviewed V2.57 USB-power ABI, not USB data/OTG-host emulation. Stock reads
     sink role as one byte, then ADC1 as a little-endian signed 32-bit sample.
     Enable all ADC descriptors so stock initialization reaches channel 1;
     other sensors remain explicitly unavailable, never EOF/uninitialized data. */
  if(data&&((count==1&&device_is(fd,"/dev/aw35615"))||
            (count==4&&adc_device(fd)))&&marker_is_one("/emu/usb-power-supported")){
    if(count==1){*(unsigned char*)data=1;return 1;} /* sink role, even unplugged */
    if(device_is(fd,"/dev/jz_adc_aux_1")){
      wr32(data,0,marker_is_one("/emu/usb-connected")?600:0);
      return 4; /* >500 connected, <100 disconnected; not calibrated millivolts */
    }
    int jack=jack_state();
    if(jack){
      /* Stock adc_check: channel 2 at 801..949 or >=1501 is a 4.4 mm plug, 1151..1349
         none; channels 0 and 3 are read and ignored. Threshold fixtures, not millivolts. */
      wr32(data,0,device_is(fd,"/dev/jz_adc_aux_2")?(jack=='4'?875:1250):0);
      return 4;
    }
    *__errno_location()=19; /* ENODEV: jack/other ADC channels not modelled */
    return -1;
  }
  long result=__read(fd,data,count);
  if(result==0&&count&&device_is(fd,"/dev/input/event0")){
    long delay[2]={0,5000000}; /* at most one 5 ms polling interval for a new key */
    sys3(__NR_nanosleep,(long)delay,0,0);
  }
  return result;
}
/* qemu-user leaves /proc/<pid>/exe of every guest process pointing at the
   interpreter, so BusyBox start-stop-daemon -x and killall-by-exe never match.
   With the opt-in marker, report the guest program instead: the path the kernel
   handed to qemu (after an optional `-0 argv0`). /proc/<pid>/cmdline is left
   alone: the original argv[0] is not recoverable (see emulator/docs/stock-init.md). */
static int proc_exe(const char*path,char*cmdline){
  const char prefix[]="/proc/",suffix[]="/cmdline";int i=0,n;
  for(;i<6;i++)if(path[i]!=prefix[i])return 0;
  if(path[i]<'0'||path[i]>'9')return 0;
  while(path[i]>='0'&&path[i]<='9'){if(i>=20)return 0;i++;}
  if(path[i]!='/'||path[i+1]!='e'||path[i+2]!='x'||path[i+3]!='e'||path[i+4])return 0;
  for(n=0;n<i;n++)cmdline[n]=path[n];
  for(i=0;suffix[i];i++)cmdline[n++]=suffix[i];
  cmdline[n]=0;return 1;
}
long readlink(const char*path,char*buf,unsigned long size){
  const char qemu[]="/qemu-mipsel-static";char cmdline[40],args[512];long i,start,end;
  long n=sys3(__NR_readlink,(long)path,(long)buf,size);
  if(n<0){*__errno_location()=-n;return -1;}
  if(n<19||!path||!proc_exe(path,cmdline))return n;
  for(i=0;i<19;i++)if(buf[n-19+i]!=qemu[i])return n;
  if(!marker_is_one("/emu/proc-exe"))return n;
  long f=sys3(__NR_open,(long)cmdline,0,0);
  if(f<0)return n;
  long length=sys3(__NR_read,f,(long)args,sizeof args-1);
  sys3(__NR_close,f,0,0);
  if(length<=0)return n;
  args[length]=0;
  for(start=0;start<length&&args[start];start++);  /* qemu's own argv[0] */
  start++;
  if(start+2<length&&args[start]=='-'&&args[start+1]=='0'&&!args[start+2]){
    start+=3;
    while(start<length&&args[start])start++;       /* the argv0 value */
    start++;
  }
  if(start>=length||args[start]!='/')return n;
  for(end=start;end<length&&args[end];end++);
  for(i=0;i<end-start&&(unsigned long)i<size;i++)buf[i]=args[start+i];
  return i;
}
/* Observe stock framebuffer copies instead of guessing which of two changed buffers
   is newer. Delegate to the guest libc (no build-host glibc dependency). */
extern void *mmap64(void*,unsigned long,int,int,int,long long);
extern void *memmove(void*,const void*,unsigned long);
static unsigned long fb_base,fb_size;
static int fb_live=-1;
/* BusyBox poweroff/reboot import libc reboot. Never pass a guest request to the
   shared kernel: publish it for the viewer's rootfs-scoped process supervisor. */
int reboot(int command){
  (void)command;
  const char request='1';
  long fd=sys3(__NR_open,(long)"/emu/power-request",1,0);
  if(fd>=0){sys3(__NR_write,fd,(long)&request,1);sys3(__NR_close,fd,0,0);}
  logmsg("[fbshim] reboot blocked; guest shutdown requested\n");
  return 0;
}
void *mmap(void*addr,unsigned long len,int prot,int flags,int fd,long offset){
  void*p=mmap64(addr,len,prot,flags,fd,(long long)offset);
  if(p!=(void*)-1&&device_is(fd,"/dev/fb0")){fb_base=(unsigned long)p;fb_size=len;fb_live=-1;}
  return p;
}
/* Who flushed a frame last: this process, by the PID it has in its own namespace.
   boot_ready.py matches it against the UI that holds the touch device (NSpid); the
   patched qemu writes the same marker when a static program pans. */
static void flushed_by_me(void){
  /* "%10d\n", written in place: a reader polling the marker never sees it empty or torn. */
  char text[11];int i=9;long v=sys3(__NR_getpid,0,0,0);
  for(int k=0;k<10;k++)text[k]=' ';text[10]='\n';
  do{text[i--]='0'+v%10;v/=10;}while(v&&i>=0);
  long fd=sys3(__NR_open,(long)"/emu/fb-flush",1/*O_WRONLY*/,0);
  if(fd>=0){sys3(__NR_write,fd,(long)text,11);sys3(__NR_close,fd,0,0);}
}
void *memcpy(void*dest,const void*src,unsigned long len){
  void*p=memmove(dest,src,len);
  unsigned long address=(unsigned long)dest;
  if(fb_base&&len&&address>=fb_base&&address-fb_base<fb_size){
    int index=(address-fb_base)/(W*H*4);
    if(index<2&&index!=fb_live){
      unsigned char value=index;
      long fd=sys3(__NR_open,(long)"/emu/fb-live",1,0);
      if(fd>=0){sys3(__NR_write,fd,(long)&value,1);sys3(__NR_close,fd,0,0);fb_live=index;}
      flushed_by_me();
    }
  }
  return p;
}
int ioctl(int fd,unsigned long req,void*arg){
  if(((req==0x2000410b&&adc_device(fd))||
      (req==0x20004e26&&device_is(fd,"/dev/aw35615"))||
      (req==0x20004d27&&device_is(fd,"/dev/sgm41513")))&&
      marker_is_one("/emu/usb-power-supported"))return 0;
  /* Unknown requests, including OTG source-role switching, still fail normally. */
  /* Only the two real volume GPIOs: active-low state maintained by the viewer.
     Unknown pins and requests retain their real failure semantics. */
  if(req==0x2000477a&&arg&&device_is(fd,"/dev/gpio")){
    /* pb20 is the 3.5 mm jack switch: 1 = plugged. Polled only without a 4.4 mm plug. */
    if(eq(arg,"pb20")){int jack=jack_state();if(jack)return jack=='3';}
    int idx=eq(arg,"pb13")?0:eq(arg,"pb14")?1:-1;
    if(idx>=0){
      char levels[2]={'1','1'};
      long f=sys3(__NR_open,(long)"/emu/volume-buttons",0,0);
      if(f>=0){sys3(__NR_read,f,(long)levels,2);sys3(__NR_close,f,0,0);}
      return levels[idx]=='0'?0:1;
    }
  }
  if((req==0x2000ef03||req==0x2000ef04)&&device_is(fd,"/dev/cst816t"))return 0;
  if((req==0x2000ef01||req==0x2000ef02)&&device_is(fd,"/dev/lcd_st77916"))return 0;
  /* Mirror the firmware's DAC attenuation writes for Web Audio. PCM capture remains
     bit-exact pre-DAC data. CS43131: 0..254 = -0.5 dB/step, 255 = mute. */
  if((req==0x80014d2d||req==0x80014d2f)&&arg&&
     (device_is(fd,"/dev/cs43131")||device_is(fd,"/dev/cs43131b")||
      device_is(fd,"/dev/cs43131c")||device_is(fd,"/dev/cs43131d"))){
    const char*path=req==0x80014d2d?"/emu/dac-left":"/emu/dac-right";
    long f=sys3(__NR_open,(long)path,1,0);
    if(f>=0){sys3(__NR_write,f,(long)arg,1);sys3(__NR_close,f,0,0);}
    return 0;
  }
  unsigned nr=req&0xff,type=(req>>8)&0xff,dir=(req>>29)&7;
  if(type==0x45&&nr==0x06&&dir==2&&arg){ const char n[]="x2000_key";int i=0;for(;i<10;i++)((char*)arg)[i]=n[i];return 9;}
  if(req==0x4600&&arg){ /* FBIOGET_VSCREENINFO */
    unsigned char*p=arg; int i;for(i=0;i<160;i++)p[i]=0;
    wr32(p,0,W); wr32(p,4,H); wr32(p,8,W); wr32(p,12,VY); wr32(p,24,BPP);
    wr32(p,32,16);wr32(p,36,8); wr32(p,44,8);wr32(p,48,8); wr32(p,56,0);wr32(p,60,8); wr32(p,68,24);wr32(p,72,8);
    logmsg("[fbshim] GET_VSCREENINFO 360x360x32\n"); return 0; }
  if(req==0x4602&&arg){ /* FBIOGET_FSCREENINFO */
    unsigned char*p=arg; int i;for(i=0;i<80;i++)p[i]=0;
    const char id[]="ingenicfb"; for(i=0;i<9;i++)p[i]=id[i];
    wr32(p,20,W*VY*(BPP/8)); wr32(p,32,2); wr32(p,44,W*(BPP/8));
    logmsg("[fbshim] GET_FSCREENINFO smem/line ok\n"); return 0; }
  if(req==0x4606&&arg){ /* FBIOPAN_DISPLAY: записать yoffset в /fbpan */
    unsigned char*p=arg; unsigned char yo[4]={p[20],p[21],p[22],p[23]};
    long fd=sys3(__NR_open,(long)"/fbpan",0x241/*O_WRONLY|O_CREAT|O_TRUNC (MIPS)*/,0644);
    if(fd>=0){sys3(__NR_write,fd,(long)yo,4);sys3(__NR_close,fd,0,0);} return 0; }
  if((req&0xff00)==0x4600){ return 0; } /* прочие fb ioctl */
  return sys3(__NR_ioctl,fd,req,(long)arg);
}
