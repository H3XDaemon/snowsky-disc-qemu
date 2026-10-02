/* Probe for a qemu-user translation gap: SO_ERROR after a refused non-blocking connect.
   The pinned qemu 7.2 returns the HOST errno (111); MIPS ECONNREFUSED is 146. */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
int main(void){
  int s=socket(AF_INET,SOCK_STREAM,0);
  fcntl(s,F_SETFL,O_NONBLOCK);
  struct sockaddr_in a={0};a.sin_family=AF_INET;a.sin_port=htons(1);inet_pton(AF_INET,"127.0.0.1",&a.sin_addr);
  int r=connect(s,(struct sockaddr*)&a,sizeof a);
  printf("connect=%d errno=%d (EINPROGRESS=%d)\n",r,errno,EINPROGRESS);
  struct pollfd p={s,POLLOUT,0};poll(&p,1,2000);
  int e=-1;socklen_t n=sizeof e;getsockopt(s,SOL_SOCKET,SO_ERROR,&e,&n);
  printf("SO_ERROR=%d ECONNREFUSED=%d %s\n",e,ECONNREFUSED,e==ECONNREFUSED?"ok":"MISMATCH");
  int s2=socket(AF_INET,SOCK_STREAM,0);r=connect(s2,(struct sockaddr*)&a,sizeof a);
  printf("blocking connect=%d errno=%d\n",r,errno);
  return e!=ECONNREFUSED;
}
