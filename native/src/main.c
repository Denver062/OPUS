#define UNICODE
#define _UNICODE
#include <windows.h>
#include <dwmapi.h>

/*
  OPUS native shell entry point. The production implementation creates a WebView2
  controller for http://127.0.0.1:47821 after starting backend/server.py.
  Keeping the window setup here in C makes Windows 11 title-bar integration native.
*/
static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM w, LPARAM l) {
  if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
  return DefWindowProc(hwnd, msg, w, l);
}
int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
  const wchar_t klass[] = L"OPUS.Window";
  WNDCLASS wc = {0}; wc.hInstance=h; wc.lpszClassName=klass; wc.lpfnWndProc=WindowProc; wc.hCursor=LoadCursor(NULL, IDC_ARROW);
  RegisterClass(&wc);
  HWND hwnd=CreateWindowEx(0,klass,L"OPUS",WS_OVERLAPPEDWINDOW|WS_VISIBLE,120,100,1280,800,NULL,NULL,h,NULL);
  BOOL dark=TRUE; DwmSetWindowAttribute(hwnd, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &dark, sizeof(dark));
  /* TODO: WebView2: extend content into title bar; reserve caption buttons; expose
     a draggable HTML region and title-bar search/quick commands in the SPA. */
  MSG msg; while(GetMessage(&msg,NULL,0,0)>0){TranslateMessage(&msg);DispatchMessage(&msg);} return 0;
}
