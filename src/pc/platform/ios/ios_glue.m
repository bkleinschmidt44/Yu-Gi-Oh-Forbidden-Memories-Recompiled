/* iOS: the thin layer the port needs on an iPhone or iPad, as android.c is
 * Android's. Everything else is the macOS ARM64 build (the translated guest
 * memory, the SDL window and the OpenGL ES path Android uses).
 *
 * - main is here: SDL_RunApp starts UIKit and calls the port's main
 *   (Memories_IosMain, src/pc/guest/main.c) once the app has launched.
 * - The player's folder is the app's Documents folder, which the Files app
 *   shows (Info.plist: UIFileSharingEnabled): saves, settings, mods, and
 *   the disc image in its game/ folder (game_files.c finds it there).
 * - The first run asks for the disc image through the system's document
 *   picker and copies it into Documents/game (Platform_SelectDisc).
 * - The program folder (languages, shipped mods) is the app bundle.
 * - stdout and stderr go to Documents/memories-log.txt: an app has no
 *   console, and that file is what a bug report needs.
 * - KEY=VALUE lines in Documents/environment.txt are set before the game
 *   starts (MEMORIES_GL_PICTURE=0 and the like, for testing).
 *
 * Compiled with Xcode's clang (build_arm64.py, link_ios), not translated. */
#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <SDL3/SDL.h>
#define SDL_MAIN_HANDLED /* this file's main calls SDL_RunApp itself */
#include <SDL3/SDL_main.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int Memories_IosMain(int argc, char **argv); /* src/pc/guest/main.c's main */
int Platform_SelectDisc(char *path, size_t size, char *why, size_t why_size);

static char documents[1024];

/* --- the document picker -------------------------------------------------- */

@interface MemoriesDiscPicker : NSObject <UIDocumentPickerDelegate>
@property(nonatomic) int done;          /* 1 picked, -1 cancelled */
@property(nonatomic, strong) NSURL *picked;
@end

@implementation MemoriesDiscPicker
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls
{
    (void)controller;
    self.picked = urls.firstObject;
    self.done = self.picked ? 1 : -1;
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller
{
    (void)controller;
    self.done = -1;
}
@end

static UIWindowScene *active_scene(void)
{
    UIWindowScene *fallback = nil;
    for (UIScene *scene in [UIApplication sharedApplication].connectedScenes) {
        if (![scene isKindOfClass:[UIWindowScene class]]) continue;
        if (scene.activationState == UISceneActivationStateForegroundActive) return (UIWindowScene *)scene;
        if (!fallback) fallback = (UIWindowScene *)scene;
    }
    return fallback;
}

/* The system's picker over a window of our own (the game's window is not
 * open yet), the run loop turned until the player chooses or cancels. With
 * asCopy the system copies the file into the app first, so no security
 * scoped access is needed and the copy can be moved into place. */
static NSURL *pick_disc(void)
{
    MemoriesDiscPicker *delegate = [MemoriesDiscPicker new];
    UIWindowScene *scene = active_scene();
    UIWindow *window = scene ? [[UIWindow alloc] initWithWindowScene:scene]
                             : [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
    NSMutableArray<UTType *> *types = [NSMutableArray array];
    UTType *bin = [UTType typeWithFilenameExtension:@"bin"];
    if (bin) [types addObject:bin];
    [types addObject:UTTypeData]; /* a .bin some app labels otherwise */
    UIDocumentPickerViewController *picker =
        [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:types asCopy:YES];
    picker.delegate = delegate;
    picker.allowsMultipleSelection = NO;
    picker.modalPresentationStyle = UIModalPresentationFormSheet;
    window.rootViewController = [UIViewController new];
    window.windowLevel = UIWindowLevelAlert;
    [window makeKeyAndVisible];
    [window.rootViewController presentViewController:picker animated:YES completion:nil];
    while (!delegate.done) {
        @autoreleasepool {
            SDL_PumpEvents();
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
        }
    }
    [picker dismissViewControllerAnimated:NO completion:nil];
    window.hidden = YES;
    return delegate.done > 0 ? delegate.picked : nil;
}

/* Choose the disc image (platform.h): 1 with its path in `path`, 0 when the
 * player quit, -1 with the reason in `why`. The chosen file is moved into
 * Documents/game, where game_files.c also looks on later launches (the app's
 * folder changes its path when the app is reinstalled). */
int Platform_SelectDisc(char *path, size_t size, char *why, size_t why_size)
{
    static const SDL_MessageBoxButtonData buttons[] = {
        {SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 0, "Quit"},
        {SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT, 1, "Choose .bin..."},
    };
    const SDL_MessageBoxData welcome = {
        SDL_MESSAGEBOX_INFORMATION, NULL, "Forbidden Memories",
        "Choose your copy of Yu-Gi-Oh! Forbidden Memories (USA, SLUS-01411): the .bin file of its "
        ".bin/.cue pair, from Files.\n\n"
        "It is copied into this app's folder (Files > On My iPhone), so this is asked only once. "
        "You can also put the .bin in that folder's \"game\" folder yourself.",
        2, buttons, NULL};
    int button = 0;
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO)) {
        snprintf(why, why_size, "Could not start: %s", SDL_GetError());
        return -1;
    }
    if (!SDL_ShowMessageBox(&welcome, &button)) button = 1; /* no box: straight to the picker */
    if (button != 1) {
        SDL_QuitSubSystem(SDL_INIT_VIDEO);
        return 0;
    }
    @autoreleasepool {
        NSURL *picked = pick_disc();
        NSFileManager *files = [NSFileManager defaultManager];
        NSString *folder = [[NSString stringWithUTF8String:documents] stringByAppendingPathComponent:@"game"];
        NSString *name = picked.lastPathComponent.length ? picked.lastPathComponent : @"disc.bin";
        NSString *target;
        NSError *error = nil;
        SDL_QuitSubSystem(SDL_INIT_VIDEO);
        if (!picked) return 0;
        if (![name.pathExtension.lowercaseString isEqualToString:@"bin"]) name = [name stringByAppendingPathExtension:@"bin"];
        target = [folder stringByAppendingPathComponent:name];
        [files createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:nil];
        [files removeItemAtPath:target error:nil];
        if (![files moveItemAtURL:picked toURL:[NSURL fileURLWithPath:target] error:&error] &&
            ![files copyItemAtURL:picked toURL:[NSURL fileURLWithPath:target] error:&error]) {
            snprintf(why, why_size, "Could not copy the disc image into the app: %s",
                     error.localizedDescription.UTF8String ?: "unknown error");
            return -1;
        }
        if (strlen(target.fileSystemRepresentation) >= size) {
            snprintf(why, why_size, "The app's folder path is too long.");
            return -1;
        }
        snprintf(path, size, "%s", target.fileSystemRepresentation);
        return 1;
    }
}

/* --- orientation ------------------------------------------------------------ */

void Ios_ApplyOrientation(int mode); /* platform.h */

static int orientation_applied = -1;

static const char *orientation_hint(int mode)
{
    return mode == 1 ? "Portrait" : mode == 2 ? "LandscapeLeft LandscapeRight Portrait" : "LandscapeLeft LandscapeRight";
}

/* What UIKit has, for the log: the scene's orientation and each window's
 * frame and what its view controller accepts. */
static void log_orientation(const char *when)
{
    @autoreleasepool {
        CGRect screen = [UIScreen mainScreen].bounds;
        fprintf(stderr, "memories-ios: orientation %s: screen %.0fx%.0f, device %ld\n", when, screen.size.width,
                screen.size.height, (long)[UIDevice currentDevice].orientation);
        for (UIScene *scene in [UIApplication sharedApplication].connectedScenes) {
            if (![scene isKindOfClass:[UIWindowScene class]]) continue;
            UIWindowScene *windows = (UIWindowScene *)scene;
            fprintf(stderr, "  scene interface %ld, bounds %.0fx%.0f\n", (long)windows.interfaceOrientation,
                    windows.coordinateSpace.bounds.size.width, windows.coordinateSpace.bounds.size.height);
            for (UIWindow *window in windows.windows) {
                UIViewController *root = window.rootViewController;
                fprintf(stderr, "  window %s%s frame %.0f,%.0f %.0fx%.0f, root %s accepts 0x%lx, view %.0fx%.0f\n",
                        window.hidden ? "(hidden) " : "", window.isKeyWindow ? "(key) " : "", window.frame.origin.x,
                        window.frame.origin.y, window.frame.size.width, window.frame.size.height,
                        root ? NSStringFromClass([root class]).UTF8String : "none",
                        root ? (unsigned long)root.supportedInterfaceOrientations : 0ul,
                        root ? root.view.bounds.size.width : 0, root ? root.view.bounds.size.height : 0);
            }
        }
    }
}

/* Video > Orientation (platform.h): SDL's view controller reads
 * SDL_HINT_ORIENTATIONS each time UIKit asks what it supports, so the hint
 * changes it; UIKit is then told to ask again and turn the window. */
void Ios_ApplyOrientation(int mode)
{
    const char *hint = orientation_hint(mode);
    UIInterfaceOrientationMask mask = mode == 1 ? UIInterfaceOrientationMaskPortrait
                                    : mode == 2 ? (UIInterfaceOrientationMaskLandscape | UIInterfaceOrientationMaskPortrait)
                                                : UIInterfaceOrientationMaskLandscape;
    if (mode == orientation_applied) return;
    orientation_applied = mode;
    log_orientation("before");
    SDL_SetHint(SDL_HINT_ORIENTATIONS, hint);
    @autoreleasepool {
        for (UIScene *scene in [UIApplication sharedApplication].connectedScenes) {
            if (![scene isKindOfClass:[UIWindowScene class]]) continue;
            UIWindowScene *windows = (UIWindowScene *)scene;
            if (@available(iOS 16.0, *)) {
                for (UIWindow *window in windows.windows)
                    [window.rootViewController setNeedsUpdateOfSupportedInterfaceOrientations];
                if (mode != 2) {
                    UIWindowSceneGeometryPreferencesIOS *wanted =
                        [[UIWindowSceneGeometryPreferencesIOS alloc] initWithInterfaceOrientations:mask];
                    [windows requestGeometryUpdateWithPreferences:wanted
                                                     errorHandler:^(NSError *error) {
                                                         fprintf(stderr, "memories-ios: orientation: %s\n",
                                                                 error.localizedDescription.UTF8String);
                                                     }];
                }
            }
        }
        if (@available(iOS 16.0, *)) {
        } else {
            [UIViewController attemptRotationToDeviceOrientation];
        }
    }
    fprintf(stderr, "memories-ios: orientation %s\n", hint);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        log_orientation("a second later");
    });
}

/* Video > Orientation as saved (Documents/settings.txt, settings.c's
 * format): read before the window is made, so the window starts the way
 * it is meant to be held rather than turning once the game is up. */
static int saved_orientation(void)
{
    char file[1100], line[256];
    FILE *in;
    int mode = 0;
    snprintf(file, sizeof(file), "%s/settings.txt", documents);
    if (!(in = fopen(file, "r"))) return 0;
    while (fgets(line, sizeof(line), in)) {
        if (!strncmp(line, "orientation=", 12)) mode = atoi(line + 12);
    }
    fclose(in);
    return mode >= 0 && mode <= 2 ? mode : 0;
}

/* --- start ----------------------------------------------------------------- */

/* KEY=VALUE lines of Documents/environment.txt (# starts a comment). */
static void read_environment(void)
{
    char file[1100], line[1024];
    FILE *in;
    snprintf(file, sizeof(file), "%s/environment.txt", documents);
    if (!(in = fopen(file, "r"))) return;
    while (fgets(line, sizeof(line), in)) {
        char *equals, *end = line + strcspn(line, "\r\n");
        *end = '\0';
        if (line[0] == '#' || !(equals = strchr(line, '='))) continue;
        *equals = '\0';
        if (line[0]) setenv(line, equals + 1, 1);
    }
    fclose(in);
}

static int start(int argc, char **argv)
{
    static char name[] = "memories-ios";
    static char *args[] = {name, NULL};
    char log[1100], game[1100];
    (void)argc;
    (void)argv;
    @autoreleasepool {
        NSString *home = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        NSString *bundle = [NSBundle mainBundle].resourcePath;
        snprintf(documents, sizeof(documents), "%s", home ? home.fileSystemRepresentation : ".");
        if (bundle) setenv("MEMORIES_PROGRAM_DIR", bundle.fileSystemRepresentation, 0);
    }
    snprintf(game, sizeof(game), "%s/game", documents);
    mkdir(game, 0755);
    snprintf(log, sizeof(log), "%s/memories-log.txt", documents);
    if (freopen(log, "w", stderr)) setvbuf(stderr, NULL, _IONBF, 0);
    freopen(log, "a", stdout);
    setenv("MEMORIES_USER_DIR", documents, 0);
    read_environment();
    /* The whole screen in landscape; no crash monitor process (an app
     * cannot start itself again) and no update check (no curl here). */
    setenv("MEMORIES_FULLSCREEN", "1", 0);
    setenv("MEMORIES_NO_MONITOR", "1", 0);
    setenv("MEMORIES_NO_UPDATE_CHECK", "1", 0);
    orientation_applied = saved_orientation();
    SDL_SetHint(SDL_HINT_ORIENTATIONS, orientation_hint(orientation_applied));
    fprintf(stderr, "memories-ios: starting with orientation %s\n", orientation_hint(orientation_applied));
    /* The game's own touch controls take the fingers; SDL's synthetic mouse
     * still reaches the menus, as on Android. */
    fprintf(stderr, "memories-ios: user folder %s, program folder %s\n", documents,
            getenv("MEMORIES_PROGRAM_DIR") ? getenv("MEMORIES_PROGRAM_DIR") : "?");
    return Memories_IosMain(1, args);
}

int main(int argc, char **argv)
{
    return SDL_RunApp(argc, argv, start, NULL);
}
