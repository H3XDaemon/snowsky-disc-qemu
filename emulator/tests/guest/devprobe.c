/* Static probe of the emulated framebuffer and input devices: what a statically linked
   guest program (a boot-layer `ui` package, diskOS's UI) sees without the preload shim.
   Prints one line per query; the emulator's tests compare them with the stock geometry.
   usage: devprobe [fb-path [touch-path [keys-path]]]        exit 0 only if every query worked */
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

static int failures;

static void fail(const char *what){ printf("%s: %s\n", what, strerror(errno)); failures++; }

static void bits(const char *label, int fd, int ev, int max){
  unsigned char map[(KEY_MAX + 7) / 8] = {0};
  int n = ioctl(fd, EVIOCGBIT(ev, sizeof map), map), i;
  if(n < 0){ fail(label); return; }
  printf("%s:", label);
  for(i = 0; i <= max; i++) if(map[i / 8] & (1 << (i % 8))) printf(" %#x", i);
  printf("\n");
}

static void absinfo(int fd, int axis){
  struct input_absinfo info;
  char label[32];
  snprintf(label, sizeof label, "abs %#x", axis);
  if(ioctl(fd, EVIOCGABS(axis), &info) < 0){ printf("%s: %s\n", label, strerror(errno)); return; }
  printf("%s: %d..%d\n", label, info.minimum, info.maximum);
}

static void input(const char *path, const char *label){
  char name[64] = "";
  struct input_id id;
  int version = 0, fd = open(path, O_RDONLY | O_NONBLOCK);
  if(fd < 0){ fail(label); return; }
  if(ioctl(fd, EVIOCGNAME(sizeof name), name) < 0) fail("name"); else printf("%s name: %s\n", label, name);
  if(ioctl(fd, EVIOCGVERSION, &version) < 0) fail("version"); else printf("%s version: %#x\n", label, version);
  if(ioctl(fd, EVIOCGID, &id) < 0) fail("id"); else printf("%s bus: %#x\n", label, id.bustype);
  bits("ev", fd, 0, EV_MAX);
  bits("keys", fd, EV_KEY, KEY_MAX);
  absinfo(fd, ABS_X); absinfo(fd, ABS_MT_POSITION_Y); absinfo(fd, ABS_MT_TRACKING_ID);
  if(ioctl(fd, EVIOCGRAB, (void *)1) < 0) fail("grab"); else printf("%s grab: ok\n", label);
  close(fd);
}

int main(int argc, char **argv){
  const char *fb = argc > 1 ? argv[1] : "/dev/fb0";
  struct fb_var_screeninfo var;
  struct fb_fix_screeninfo fix;
  int fd = open(fb, O_RDWR);
  if(fd < 0){ fail("open fb"); return 2; }
  if(ioctl(fd, FBIOGET_VSCREENINFO, &var) < 0){ fail("vinfo"); return 2; }
  if(ioctl(fd, FBIOGET_FSCREENINFO, &fix) < 0){ fail("finfo"); return 2; }
  printf("fb: %ux%u virtual %ux%u bpp %u offsets r%u g%u b%u a%u\n", var.xres, var.yres, var.xres_virtual,
         var.yres_virtual, var.bits_per_pixel, var.red.offset, var.green.offset, var.blue.offset, var.transp.offset);
  printf("fix: %s smem %u line %u visual %u\n", fix.id, fix.smem_len, fix.line_length, fix.visual);
  void *map = mmap(NULL, fix.smem_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if(map == MAP_FAILED) fail("mmap"); else { printf("mmap: ok\n"); munmap(map, fix.smem_len); }
  var.yoffset = var.yres; var.activate = FB_ACTIVATE_NOW;          /* show the second sub-buffer */
  if(ioctl(fd, FBIOPAN_DISPLAY, &var) < 0) fail("pan");
  if(ioctl(fd, FBIOGET_VSCREENINFO, &var) < 0) fail("vinfo after pan"); else printf("pan: yoffset %u\n", var.yoffset);
  if(ioctl(fd, FBIOBLANK, FB_BLANK_UNBLANK) < 0) fail("blank"); else printf("blank: ok\n");
  close(fd);
  input(argc > 2 ? argv[2] : "/dev/input/event1", "touch");
  input(argc > 3 ? argv[3] : "/dev/input/event0", "keys");
  return failures ? 1 : 0;
}
