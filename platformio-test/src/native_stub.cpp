// native 환경 pio run 진입점 — 실제 실행용 코드 없음
#if defined(NATIVE) || defined(UNIX_HOST_DUINO)
int main() { return 0; }
#endif
