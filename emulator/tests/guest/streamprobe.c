/* Drives the audio shim's own functions step by step, outside a guest, so its text
   output can be read by a firmware-free test. Built together with tinyshim.c. */
struct pcm;
struct pcm *pcm_open(unsigned card, unsigned device, unsigned flags, const void *config);
int pcm_write(struct pcm *pcm, const void *data, unsigned count);
int pcm_close(struct pcm *pcm);

int main(int argc, char **argv){
  /* channels, rate, period_size, period_count, format (7 = 32-bit) */
  unsigned config[5] = {2, 44100, 1024, 4, 7};
  static int samples[2 * 441];
  const char *until = argc > 1 ? argv[1] : "close";
  struct pcm *pcm = pcm_open(0, 3, 0, config);
  int i;
  if (!pcm) return 1;
  if (until[0] == 'o') return 0;                       /* open */
  for (i = 0; i < 2 * 441; ++i) samples[i] = i * 1000;
  if (pcm_write(pcm, samples, sizeof samples)) return 2;
  if (until[0] == 's' && until[1] == 'a') return 0;    /* samples */
  for (i = 0; i < 2 * 441; ++i) samples[i] = 0;
  if (pcm_write(pcm, samples, sizeof samples)) return 3;
  if (until[0] == 's') return 0;                       /* silence */
  return pcm_close(pcm);                               /* close */
}
