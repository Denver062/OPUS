#define COBJMACROS
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <dwmapi.h>
#include <WebView2.h>
#include <WebView2Loader.h>

/*
  The UI and controller bind to 127.0.0.1 only. WebView2 is loaded from the
  Evergreen runtime supplied with Windows/Edge, while the SDK loader is linked
  by CMake. This file intentionally uses C COM vtables rather than C++.
*/
static HWND window_handle;
static ICoreWebView2Controller *controller;
static PROCESS_INFORMATION backend_process;

typedef struct EnvironmentHandler {
  ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler iface;
  ULONG references;
  HWND hwnd;
} EnvironmentHandler;
typedef struct ControllerHandler {
  ICoreWebView2CreateCoreWebView2ControllerCompletedHandler iface;
  ULONG references;
  HWND hwnd;
} ControllerHandler;

static HRESULT STDMETHODCALLTYPE environment_query(
  ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *self, REFIID iid, void **out) {
  if (!out) return E_POINTER;
  if (IsEqualIID(iid, &IID_IUnknown) ||
      IsEqualIID(iid, &IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler)) {
    *out = self; IUnknown_AddRef((IUnknown *)self); return S_OK;
  }
  *out = NULL; return E_NOINTERFACE;
}
static HRESULT STDMETHODCALLTYPE controller_query(
  ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *self, REFIID iid, void **out) {
  if (!out) return E_POINTER;
  if (IsEqualIID(iid, &IID_IUnknown) ||
      IsEqualIID(iid, &IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler)) {
    *out = self; IUnknown_AddRef((IUnknown *)self); return S_OK;
  }
  *out = NULL; return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE add_ref(IUnknown *self) {
  EnvironmentHandler *env = (EnvironmentHandler *)self;
  return InterlockedIncrement((LONG *)&env->references);
}
static ULONG STDMETHODCALLTYPE release(IUnknown *self) {
  EnvironmentHandler *env = (EnvironmentHandler *)self;
  ULONG value = InterlockedDecrement((LONG *)&env->references);
  if (!value) HeapFree(GetProcessHeap(), 0, env);
  return value;
}

static void resize_webview(HWND hwnd) {
  if (controller) {
    RECT area; GetClientRect(hwnd, &area);
    ICoreWebView2Controller_put_Bounds(controller, area);
  }
}

static HRESULT STDMETHODCALLTYPE controller_invoke(
  ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *self,
  HRESULT result, ICoreWebView2Controller *created) {
  ControllerHandler *handler = (ControllerHandler *)self;
  if (FAILED(result) || !created) return result;
  controller = created;
  ICoreWebView2Controller_AddRef(controller);
  ICoreWebView2Controller_put_IsVisible(controller, TRUE);
  resize_webview(handler->hwnd);
  ICoreWebView2 *webview = NULL;
  if (SUCCEEDED(ICoreWebView2Controller_get_CoreWebView2(controller, &webview))) {
    ICoreWebView2_Navigate(webview, L"http://127.0.0.1:47821/");
    ICoreWebView2_Release(webview);
  }
  return S_OK;
}
static const ICoreWebView2CreateCoreWebView2ControllerCompletedHandlerVtbl CONTROLLER_VTBL = {
  controller_query,
  (ULONG (STDMETHODCALLTYPE *)(ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *))add_ref,
  (ULONG (STDMETHODCALLTYPE *)(ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *))release,
  controller_invoke
};

static HRESULT STDMETHODCALLTYPE environment_invoke(
  ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *self,
  HRESULT result, ICoreWebView2Environment *environment) {
  EnvironmentHandler *handler = (EnvironmentHandler *)self;
  if (FAILED(result) || !environment) return result;
  ControllerHandler *next = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*next));
  if (!next) return E_OUTOFMEMORY;
  next->iface.lpVtbl = &CONTROLLER_VTBL; next->references = 1; next->hwnd = handler->hwnd;
  return ICoreWebView2Environment_CreateCoreWebView2Controller(environment, handler->hwnd, &next->iface);
}
static const ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandlerVtbl ENVIRONMENT_VTBL = {
  environment_query,
  (ULONG (STDMETHODCALLTYPE *)(ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *))add_ref,
  (ULONG (STDMETHODCALLTYPE *)(ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *))release,
  environment_invoke
};

static BOOL start_backend(void) {
  wchar_t module[MAX_PATH], command[MAX_PATH * 2];
  GetModuleFileNameW(NULL, module, MAX_PATH);
  wchar_t *last = wcsrchr(module, L'\\'); if (!last) return FALSE; *last = L'\0';
  swprintf(command, MAX_PATH * 2, L"python.exe \"%s\\backend\\server.py\"", module);
  STARTUPINFOW startup; ZeroMemory(&startup, sizeof(startup));
  startup.cb = sizeof(startup); startup.dwFlags = STARTF_USESHOWWINDOW; startup.wShowWindow = SW_HIDE;
  return CreateProcessW(NULL, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, module, &startup, &backend_process);
}
static void start_webview(HWND hwnd) {
  EnvironmentHandler *handler = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*handler));
  if (!handler) return;
  handler->iface.lpVtbl = &ENVIRONMENT_VTBL; handler->references = 1; handler->hwnd = hwnd;
  CreateCoreWebView2EnvironmentWithOptions(NULL, NULL, NULL, &handler->iface);
}

static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM w, LPARAM l) {
  switch (msg) {
    case WM_SIZE: resize_webview(hwnd); return 0;
    case WM_CREATE: start_backend(); SetTimer(hwnd, 1, 500, NULL); return 0;
    case WM_TIMER:
      if (w == 1) { KillTimer(hwnd, 1); start_webview(hwnd); }
      return 0;
    case WM_DESTROY:
      if (controller) { ICoreWebView2Controller_Close(controller); ICoreWebView2Controller_Release(controller); controller = NULL; }
      if (backend_process.hProcess) { TerminateProcess(backend_process.hProcess, 0); CloseHandle(backend_process.hProcess); CloseHandle(backend_process.hThread); }
      PostQuitMessage(0); return 0;
  }
  return DefWindowProcW(hwnd, msg, w, l);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
  (void)previous; (void)command;
  const wchar_t class_name[] = L"OPUS.Window";
  WNDCLASSW klass = {0}; klass.hInstance = instance; klass.lpszClassName = class_name; klass.lpfnWndProc = WindowProc; klass.hCursor = LoadCursor(NULL, IDC_ARROW);
  RegisterClassW(&klass);
  HWND hwnd = CreateWindowExW(0, class_name, L"OPUS", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 120, 100, 1280, 800, NULL, NULL, instance, NULL);
  window_handle = hwnd;
  BOOL dark = TRUE; COLORREF background = RGB(16, 17, 22);
  DwmSetWindowAttribute(hwnd, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &dark, sizeof(dark));
  DwmSetWindowAttribute(hwnd, 35 /* DWMWA_CAPTION_COLOR */, &background, sizeof(background));
  ShowWindow(hwnd, show);
  MSG message; while (GetMessageW(&message, NULL, 0, 0) > 0) { TranslateMessage(&message); DispatchMessageW(&message); }
  return 0;
}
