/* Static probe of the guest's view of another process: what BusyBox pgrep/pidof/ps and
   start-stop-daemon read. usage:
     procprobe sleep          stay alive for a minute, as a process to look at
     procprobe <pid>          print /proc/<pid>/cmdline (fields joined by '|') and /proc/<pid>/exe */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv){
  char path[64], buf[4096];
  if(argc < 2){ fprintf(stderr, "usage: procprobe sleep|<pid>\n"); return 2; }
  if(strcmp(argv[1], "sleep") == 0){ sleep(60); return 0; }
  snprintf(path, sizeof path, "/proc/%s/cmdline", argv[1]);
  int fd = open(path, O_RDONLY);
  if(fd < 0){ perror("cmdline"); return 1; }
  int n = read(fd, buf, sizeof buf - 1); close(fd);
  if(n < 0){ perror("read"); return 1; }
  if(n > 0 && buf[n - 1] == 0) n--;
  for(int i = 0; i < n; i++) if(buf[i] == 0) buf[i] = '|';
  buf[n] = 0;
  printf("cmdline: %s\n", buf);
  snprintf(path, sizeof path, "/proc/%s/exe", argv[1]);
  n = readlink(path, buf, sizeof buf - 1);
  if(n < 0){ perror("exe"); return 1; }
  buf[n] = 0;
  printf("exe: %s\n", buf);
  return 0;
}
