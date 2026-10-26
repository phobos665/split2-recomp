cmake_minimum_required(VERSION 3.20)

# TimeSplitters 2, statically recompiled on the xboxrecomp toolkit.
#
# Build with scripts/build.py, which lifts the game first. The generated
# sources in src/recomp/gen/ come from your own copy of the game and are
# never committed.

# C and C++: the toolkit's renderer has C++ in it (the DXC loader, VMA), so
# the executable links with the C++ driver. This repository's sources are C.
project(split2_recomp C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_definitions(
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

set(XBOXRECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/xboxrecomp" CACHE PATH
    "Path to the xboxrecomp toolkit (the submodule by default)")

if(NOT EXISTS "${XBOXRECOMP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "xboxrecomp not found at ${XBOXRECOMP_DIR}. "
        "Run: git submodule update --init")
endif()

# Checks that every call preserves ebx/esi/edi and esp. Set before
# add_subdirectory: the check is emitted into the generated game code but
# its logger lives in xbox_kernel. See the toolkit's templates/new-game.
option(RECOMP_ABI_CHECK "Verify callee-saved registers across every call" OFF)
if(RECOMP_ABI_CHECK)
    add_compile_definitions(RECOMP_ABI_CHECK)
endif()

add_subdirectory(${XBOXRECOMP_DIR} ${CMAKE_BINARY_DIR}/xboxrecomp)

# CONFIGURE_DEPENDS so a re-lift that adds or removes a chunk is picked up
# without a manual re-configure.
file(GLOB RECOMP_GEN_SOURCES CONFIGURE_DEPENDS "src/recomp/gen/*.c")
if(NOT RECOMP_GEN_SOURCES)
    message(FATAL_ERROR "No generated sources in src/recomp/gen. "
        "Lift the game first: py -3 scripts/build.py")
endif()
# Which release of the game those were lifted from (PAL, USA), written beside
# them by scripts/build.py; src/main.c and src/recomp_manual.c include it.
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/recomp/ts2_region.h")
    message(FATAL_ERROR "src/recomp/ts2_region.h is missing: it names the release "
        "that was lifted. Run: py -3 scripts/build.py")
endif()

set(SPLIT2_SOURCES
    src/main.c
    src/recomp_manual.c
    ${RECOMP_GEN_SOURCES}
)

# On Android the engine is libmain.so, which SDL's Java activity loads and
# enters through SDL_main (the toolkit's src/host/android_main.c), and the
# game is libgame.so, which the device compiles from the player's disc and
# libmain.so loads (the toolkit's cmake/android.cmake). main() is renamed for
# it to call.
if(ANDROID)
    add_library(${PROJECT_NAME} OBJECT ${SPLIT2_SOURCES})
    set_target_properties(${PROJECT_NAME} PROPERTIES POSITION_INDEPENDENT_CODE ON)
    set_source_files_properties(src/main.c PROPERTIES
        COMPILE_DEFINITIONS main=recomp_title_main)
    xboxrecomp_android_libraries(${PROJECT_NAME})
else()
    add_executable(${PROJECT_NAME} ${SPLIT2_SOURCES})
endif()

# A windowed program on Windows (WinMain, no console); a plain executable
# elsewhere, whose main() hands the title its own thread (host_main_posix).
if(WIN32)
    set_target_properties(${PROJECT_NAME} PROPERTIES WIN32_EXECUTABLE ON)
endif()

target_link_libraries(${PROJECT_NAME} PRIVATE xboxrecomp)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/recomp
    ${XBOXRECOMP_DIR}/include
)

# Off Windows the toolkit's libraries bring their own (pthreads, dl, SDL3,
# OpenSSL).
if(WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE
        d3d11
        dxgi
        dxguid
        xinput
        winmm
        dbghelp     # lets the crash handler name the generated function that faulted
    )
else()
    # The POSIX fault report names a host pc with dladdr, which sees only
    # exported symbols: export the generated functions.
    set_target_properties(${PROJECT_NAME} PROPERTIES ENABLE_EXPORTS ON)
endif()

if(MSVC)
    # /DEBUG: a PDB in every configuration, so a crash names sub_XXXXXXXX.
    target_link_options(${PROJECT_NAME} PRIVATE /LARGEADDRESSAWARE /DEBUG)
    target_compile_options(${PROJECT_NAME} PRIVATE /bigobj /MP)
    # Lifted code reads ebp before writing it by design (fpo_leaf functions
    # inherit the caller's frame), which /RTC1 aborts on through a message box.
    string(REGEX REPLACE "/RTC[1csu]+" "" CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG}")
endif()

# The settings window: video options, input bindings, then starts the game.
if(COMMAND recomp_add_launcher)
    recomp_add_launcher(${PROJECT_NAME}_launcher ${PROJECT_NAME}.exe)
endif()
