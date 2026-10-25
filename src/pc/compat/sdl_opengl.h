/* SDL_opengl.h, also on iOS. SDL leaves its OpenGL 1.x declarations out on
 * iOS ("no OpenGL"), but the port's GL code is the Android port's: OpenGL ES
 * 3 through SDL's opengles2 renderer, with the few desktop-only calls on
 * paths that never run there stubbed in gl_desktop_none.c, and every function
 * past 1.1 looked up with SDL_GL_GetProcAddress. The 1.1 declarations it
 * uses directly (glBindTexture, glDrawArrays, ...) are OpenGL ES's own and
 * link against OpenGLES.framework. */
#ifndef MEMORIES_COMPAT_SDL_OPENGL_H
#define MEMORIES_COMPAT_SDL_OPENGL_H
#include <SDL3/SDL_platform.h>
#if defined(MEMORIES_IOS) && defined(SDL_PLATFORM_IOS)
#undef SDL_PLATFORM_IOS
#include <SDL3/SDL_opengl.h>
#define SDL_PLATFORM_IOS 1
#else
#include <SDL3/SDL_opengl.h>
#endif
#endif
