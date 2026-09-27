cmake_minimum_required(VERSION 3.24)
project(OPUS LANGUAGES C)

include(FetchContent)
FetchContent_Declare(webview2
  URL https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.2903.40
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_MakeAvailable(webview2)

add_executable(OPUS WIN32 src/main.c)
target_compile_definitions(OPUS PRIVATE UNICODE _UNICODE COBJMACROS)
target_include_directories(OPUS PRIVATE "${webview2_SOURCE_DIR}/build/native/include")
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  set(OPUS_WEBVIEW2_ARCH x64)
else()
  set(OPUS_WEBVIEW2_ARCH x86)
endif()
target_link_libraries(OPUS PRIVATE
  "${webview2_SOURCE_DIR}/build/native/${OPUS_WEBVIEW2_ARCH}/WebView2LoaderStatic.lib"
  dwmapi ole32 shell32)

# A distributable executable carries its local UI/API assets next to the binary.
add_custom_command(TARGET OPUS POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_LIST_DIR}/../backend" "$<TARGET_FILE_DIR:OPUS>/backend"
  COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_LIST_DIR}/../catalog" "$<TARGET_FILE_DIR:OPUS>/catalog"
  COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_LIST_DIR}/../web" "$<TARGET_FILE_DIR:OPUS>/web")
