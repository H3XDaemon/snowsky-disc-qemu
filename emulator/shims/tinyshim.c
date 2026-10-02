/* Freestanding tinyalsa interposer: capture the PCM the LOCAL DAC path writes, no hardware.
 *
 * mq_player links both libasound and libtinyalsa; LOCAL playback (the internal CS43131) goes
 * through tinyalsa: pcm_params_get() to validate the card, then pcm_open()/pcm_write() to the DAC.
 * Under emulation there's no card, so pcm_params_get()/pcm_open() would fail and playback aborts
 * ("error config pcm params"). We interpose libtinyalsa (preloaded via /etc/ld.so.preload, ahead
 * of libtinyalsa.so.1): pcm_params_* report a permissive card, pcm_open returns a fake handle and
 * records the config, and pcm_write appends the raw PCM to /audio.pcm. tinyalsa's pcm_write takes
 * a BYTE count, so capture is exact without knowing the frame size.
 *
 * Freestanding (-nostdlib, raw MIPS syscalls) — device glibc 2.29 != host toolchain glibc, same as
 * fbshim. The negotiated format (channels, sample-bytes, rate) goes to /audio.fmt as 3x u32 LE so
 * the host can wrap /audio.pcm into a WAV.
 */
#define __NR_open  4005
#define __NR_write 4004
#define __NR_close 4006
#define __NR_nanosleep 4166
#define __NR_getpid 4020
#define __NR_rename 4038
#define O_WCT 0x301   /* MIPS O_WRONLY|O_CREAT|O_TRUNC  */
#ifndef TINYSHIM_ROOT  /* tests run the shim outside a chroot and prefix its files */
#define TINYSHIM_ROOT ""
#endif

static long sys3(long n, long a, long b, long c){
  register long v0 asm("$2")=n, a0 asm("$4")=a, a1 asm("$5")=b, a2 asm("$6")=c;
  register long a3 asm("$7");
  asm volatile("syscall":"+r"(v0),"=r"(a3):"r"(a0),"r"(a1),"r"(a2)
    :"memory","$8","$9","$10","$11","$12","$13","$14","$15","$24","$25","hi","lo");
  return a3 ? -v0 : v0;
}

static char g_pcm[16], g_params[16];
static int g_fd = -1, g_ch = 2, g_sb = 4;
static unsigned g_rate = 48000;
static unsigned g_buffer_frames = 8192;

static void trace(const char *s){
  unsigned n = 0; while (s[n]) ++n;
  sys3(__NR_write, 2, (long)s, n);
}

#ifndef TINYSHIM_NO_FOPEN
/* procfs belongs to the host kernel; redirect only the guest's card discovery. */
extern void *fopen64(const char *, const char *);
void *fopen(const char *path, const char *mode){
  const char *card_path = "/proc/asound/cards";
  unsigned i = 0;
  while (path[i] && path[i] == card_path[i]) ++i;
  if (!path[i] && !card_path[i]) path = "/etc/asound.cards";
  return fopen64(path, mode);
}
#endif

/* What a program on the player reads in /proc/asound/card0/pcm3p/sub0: here under
 * /emu/asound (a real procfs cannot be extended), kept in step with the stock stream.
 * Readers never see a half-written file: write beside it, then rename. */
static void publish(const char *name, const char *text, unsigned n){
  static const char stream[] = TINYSHIM_ROOT "/emu/asound/card0/pcm3p/sub0/";
  char path[sizeof stream + 16], fresh[sizeof stream + 20];
  unsigned i = 0, k = 0;
  for (; i < sizeof stream - 1; ++i) path[i] = stream[i];
  while (name[k]) path[i++] = name[k++];
  path[i] = 0;
  for (k = 0; k < i; ++k) fresh[k] = path[k];
  fresh[k++] = '.'; fresh[k++] = 'n'; fresh[k] = 0;
  long fd = sys3(__NR_open, (long)fresh, O_WCT, 0644);
  if (fd < 0) return;                       /* older setup without the tree: nothing to keep */
  sys3(__NR_write, fd, (long)text, n);
  sys3(__NR_close, fd, 0, 0);
  sys3(__NR_rename, (long)fresh, (long)path, 0);
}
static unsigned put_s(char *b, unsigned n, const char *s){ while (*s) b[n++] = *s++; return n; }
static unsigned put_u(char *b, unsigned n, unsigned v){
  char d[10]; int k = 0;
  do { d[k++] = '0' + v % 10; v /= 10; } while (v);
  while (k) b[n++] = d[--k];
  return n;
}
static unsigned g_period = 1024;
static int g_stream = -1, g_audible = -1;
static void stream_state(int state){        /* 0 closed, 1 PREPARED, 2 RUNNING */
  char b[200]; unsigned n;
  if (state == g_stream) return;
  g_stream = state;
  if (!state){ publish("status", "closed\n", 7); publish("hw_params", "closed\n", 7); return; }
  n = put_s(b, 0, "access: RW_INTERLEAVED\nformat: ");
  n = put_s(b, n, g_sb == 2 ? "S16_LE" : g_sb == 3 ? "S24_3LE" : "S32_LE");
  n = put_s(b, n, "\nsubformat: STD\nchannels: "); n = put_u(b, n, (unsigned)g_ch);
  n = put_s(b, n, "\nrate: "); n = put_u(b, n, g_rate);
  n = put_s(b, n, " ("); n = put_u(b, n, g_rate);
  n = put_s(b, n, "/1)\nperiod_size: "); n = put_u(b, n, g_period);
  n = put_s(b, n, "\nbuffer_size: "); n = put_u(b, n, g_buffer_frames);
  n = put_s(b, n, "\n");
  publish("hw_params", b, n);
  n = put_s(b, 0, "state: "); n = put_s(b, n, state == 2 ? "RUNNING" : "PREPARED");
  n = put_s(b, n, "\nowner_pid   : "); n = put_u(b, n, (unsigned)sys3(__NR_getpid, 0, 0, 0));
  n = put_s(b, n, "\n");
  publish("status", b, n);
}
/* Stock keeps the stream running while paused and feeds it zeros. One byte tells the
 * two apart for tests and the viewer: c closed, s silence, p samples. */
static void audible(int state){
  static const char mark[3] = {'c', 's', 'p'};
  if (state == g_audible) return;
  g_audible = state;
  long fd = sys3(__NR_open, (long)(TINYSHIM_ROOT "/emu/audio-state"), 1 /* O_WRONLY: fixed-width overwrite */, 0);
  if (fd < 0) return;
  sys3(__NR_write, fd, (long)&mark[state], 1);
  sys3(__NR_close, fd, 0, 0);
}

static int fmt_write(void){
  long fd = sys3(__NR_open, (long)(TINYSHIM_ROOT "/audio.fmt"), O_WCT, 0644);
  if (fd < 0) return -1;
  unsigned r[3] = {(unsigned)g_ch,(unsigned)g_sb,g_rate};
  long written = sys3(__NR_write,fd,(long)r,sizeof r);
  sys3(__NR_close,fd,0,0);
  return written == sizeof r ? 0 : -1;
}

/* struct pcm_config: channels@0, rate@4, period_size@8, period_count@12, format@16 (u32 each) */
struct pcm *pcm_open(unsigned card, unsigned device, unsigned flags, const void *config){
  trace("[tinyshim] pcm_open\n");
  (void)card;(void)device;
  if ((flags & 0x10000000) || !config) return (struct pcm *)0; /* output only */
  if (g_fd >= 0) sys3(__NR_close, g_fd, 0, 0);
  g_fd = -1;
  if (config){
    const unsigned *c = (const unsigned *)config;
    if (!c[0] || c[0] > 8 || !c[1] || c[1] > 768000) return (struct pcm *)0;
    if (c[0]) g_ch = (int)c[0];
    if (c[1]) g_rate = c[1];
    unsigned fmt = c[4]; /* Vendor enum: the stock PCM path uses these signed LE formats. */
    if (fmt != 0 && fmt != 5 && fmt != 7) return (struct pcm *)0;
    g_sb = fmt == 0 ? 2 : fmt == 5 ? 3 : 4;
    g_buffer_frames = c[2]*c[3];
    g_period = c[2];
    g_fd = sys3(__NR_open, (long)(TINYSHIM_ROOT "/audio.pcm"), O_WCT, 0644);
    if (g_fd < 0) return (struct pcm *)0;
    if (fmt_write() < 0){ sys3(__NR_close,g_fd,0,0); g_fd=-1; return (struct pcm *)0; }
  }
  g_stream = -1;                            /* a new configuration is always published */
  stream_state(1);
  audible(1);
  return (struct pcm *)g_pcm;
}
int pcm_close(struct pcm *p){
  (void)p;
  if(g_fd >= 0) sys3(__NR_close,g_fd,0,0);
  g_fd=-1;
  stream_state(0);
  audible(0);
  return 0;
}
int pcm_is_ready(const struct pcm *p){ (void)p; return g_fd >= 0; }
unsigned pcm_get_buffer_size(const struct pcm *p){ (void)p; return g_buffer_frames; }
unsigned pcm_frames_to_bytes(const struct pcm *p, unsigned frames){ (void)p; return frames*g_ch*g_sb; }
unsigned pcm_bytes_to_frames(const struct pcm *p, unsigned bytes){ (void)p; return bytes/(g_ch*g_sb); }
const char *pcm_get_error(const struct pcm *p){ (void)p; return ""; }

int pcm_write(struct pcm *p, const void *data, unsigned count){
  (void)p;
  if (g_fd < 0 || !data) return -1;
  if (g_fd >= 0 && data && count){
    unsigned off = 0;
    while (off < count){
      long w = sys3(__NR_write, g_fd, (long)((const char*)data + off), count - off);
      if (w == -4) continue; /* EINTR */
      if (w <= 0) return -1;
      off += (unsigned)w;
    }
  }
  if (count){
    unsigned i = 0;
    while (i < count && !((const char*)data)[i]) ++i;
    stream_state(2);
    audible(i < count ? 2 : 1);
  }
  /* A real DAC blocks until buffer space is available. Bound the emulated sink
   * too, including firmware-generated silence, so idle writes cannot flood disk. */
  unsigned frames = count / (g_ch*g_sb);
  long delay[2] = {frames/g_rate, (long)((frames%g_rate)*1000/g_rate)*1000000};
  long remaining[2];
  while (sys3(__NR_nanosleep,(long)delay,(long)remaining,0) == -4){
    delay[0]=remaining[0]; delay[1]=remaining[1];
  }
  return 0;
}
int pcm_read(struct pcm *p, void *data, unsigned count){ (void)p;(void)data;(void)count; return -1; }

/* card capability query — report a permissive card so the config validation passes */
struct pcm_params *pcm_params_get(unsigned card, unsigned device, unsigned flags){ trace("[tinyshim] pcm_params_get\n"); (void)card;(void)device;(void)flags; return (struct pcm_params *)g_params; }
void pcm_params_free(struct pcm_params *p){ (void)p; }
unsigned pcm_params_get_min(const struct pcm_params *p, int param){ (void)p;(void)param; return 1; }
unsigned pcm_params_get_max(const struct pcm_params *p, int param){ (void)p;(void)param; return 384000; }
