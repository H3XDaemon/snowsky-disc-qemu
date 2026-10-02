/* Static, libc-free MIPS probe: reads GPIO port B PxPIN the way a boot-stage
   program does on the player (no ld.so.preload shim can help it).
   Prints the raw word as 0xXXXXXXXX, or "error <step> <errno>". */
#define NR_write 4004
#define NR_open 4005
#define NR_exit 4001
#define NR_mmap2 4210
static long sys6(long n,long a,long b,long c,long d,long e,long f){
  register long v0 asm("$2")=n,a0 asm("$4")=a,a1 asm("$5")=b,a2 asm("$6")=c,a3 asm("$7")=d;
  asm volatile("addiu $29,$29,-32\n\tsw %[e],16($29)\n\tsw %[f],20($29)\n\tsyscall\n\taddiu $29,$29,32"
    :"+r"(v0),"+r"(a3):"r"(a0),"r"(a1),"r"(a2),[e]"r"(e),[f]"r"(f)
    :"memory","$8","$9","$10","$11","$12","$13","$14","$15","$24","$25","hi","lo");
  return a3?-v0:v0;
}
static void put(const char*s){long n=0;while(s[n])n++;sys6(NR_write,1,(long)s,n,0,0,0);}
static void fail(const char*step,long code){
  char digits[12];int n=11;digits[n]=0;code=-code;
  do{digits[--n]='0'+code%10;code/=10;}while(code);
  put("error ");put(step);put(" ");put(digits+n);put("\n");
  sys6(NR_exit,1,0,0,0,0,0);
}
void __start(void){
  static const char hex[]="0123456789ABCDEF";
  char out[12]="0x";int i;
  long fd=sys6(NR_open,(long)"/dev/mem",0x4010/*O_RDONLY|O_SYNC (MIPS)*/,0,0,0,0);
  if(fd<0)fail("open",fd);
  /* 4096 bytes, PROT_READ, MAP_SHARED, page offset of 0x10010000 */
  long map=sys6(NR_mmap2,0,4096,1,1,fd,0x10010000>>12);
  if(map<0&&map>-4096)fail("mmap",map);
  unsigned value=*(volatile unsigned*)(map+0x100);
  for(i=0;i<8;i++)out[2+i]=hex[(value>>(28-4*i))&15];
  out[10]='\n';out[11]=0;put(out);
  sys6(NR_exit,0,0,0,0,0,0);
}
