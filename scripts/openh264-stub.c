#include <stddef.h>

typedef struct { unsigned int uMajor, uMinor, uRevision, uReserved; } OpenH264Version;

int WelsCreateSVCEncoder(void **ppEncoder) {
  if (ppEncoder) *ppEncoder = NULL;
  return 1;
}

void WelsDestroySVCEncoder(void *pEncoder) { (void)pEncoder; }

OpenH264Version WelsGetCodecVersion(void) {
  OpenH264Version v = {2, 6, 0, 0};
  return v;
}

void WelsGetCodecVersionEx(OpenH264Version *pVersion) {
  if (pVersion) { pVersion->uMajor = 2; pVersion->uMinor = 6; pVersion->uRevision = 0; pVersion->uReserved = 0; }
}

const char *iamdirector_openh264_stub(void) { return "stub"; }
