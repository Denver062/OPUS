cmake_minimum_required(VERSION 3.21)
project(OPUS LANGUAGES C)
add_executable(OPUS WIN32 src/main.c)
target_compile_definitions(OPUS PRIVATE UNICODE _UNICODE)
target_link_libraries(OPUS PRIVATE dwmapi ole32 shell32)
# Install the Microsoft.Web.WebView2 NuGet package and add its include/lib paths here.
# The C host is intentionally separate from the local Python API so the UI can be
# tested before WebView2 SDK integration is complete.
