#ifndef __uvcham_h__
#define __uvcham_h__

/* Version: 1.29030.20250722 */
/* Win32:
     (a) x86: XP SP3 or above; CPU supports SSE2 instruction set or above
     (b) x64: Win7 or above
*/

#ifdef __cplusplus
extern "C" {
#endif

/**********************************************************************************/
/* Uvcham_enum (optional)                                                         */
/* ----> Uvcham_open                                                              */
/* ----> enum resolutions, set resolution, set exposure time, etc                 */
/* ----> Uvcham_start                                                             */
/* ----> callback for image and events                                            */
/* ----> Uvcham_close                                                             */
/**********************************************************************************/
#define UVCHAM_MAX                 16

#define UVCHAM_FLIPHORZ            0x00000002    /* flip horizontal */
#define UVCHAM_FLIPVERT            0x00000003    /* flip vertical */
#define UVCHAM_AEXPOTARGET         0x00000004    /* exposure compensation */
#define UVCHAM_DENOISE             0x00000005    /* denoise */
#define UVCHAM_WBROILEFT           0x00000006    /* white balance mode roi: left */
#define UVCHAM_WBROIWIDTH          0x00000007    /* white balance mode roi: width, width >= UVCHAM_WBROI_WIDTH_MIN */
#define UVCHAM_WBROITOP            0x00000008    /* white balance mode roi: top */
#define UVCHAM_WBROIHEIGHT         0x0000000a    /* white balance mode roi: height, height >= UVCHAM_WBROI_HEIGHT_MIN */
#define UVCHAM_YEAR                0x0000000b    /* firmware version: year */
#define UVCHAM_MONTH               0x0000000c    /* firmware version: month */
#define UVCHAM_DAY                 0x0000000d    /* firmware version: day */
#define UVCHAM_WBMODE              0x00000010    /* white balance mode: 0 = manual, 1 = auto, 2 = roi */
#define UVCHAM_EXPOTIME            0x00000011    /* exposure time */
#define UVCHAM_AEXPO               0x00000013    /* auto exposure: 0 = manual, 1 = auto */
#define UVCHAM_SHARPNESS           0x00000016
#define UVCHAM_SATURATION          0x00000017
#define UVCHAM_GAMMA               0x00000018
#define UVCHAM_CONTRAST            0x00000019
#define UVCHAM_BRIGHTNESS          0x0000001a
#define UVCHAM_HZ                  0x0000001b    /* 0 -> 60HZ AC;  1 -> 50Hz AC;  2 -> DC */
#define UVCHAM_WBRED               0x0000001c    /* white balance: R/G/B gain */
#define UVCHAM_WBGREEN             0x0000001d    /* white balance: R/G/B gain */
#define UVCHAM_WBBLUE              0x0000001e    /* white balance: R/G/B gain */
#define UVCHAM_HUE                 0x0000001f
#define UVCHAM_CHROME              0x00000020    /* color(0)/grey(1) */
#define UVCHAM_AFPOSITION          0x00000021    /* auto focus sensor board positon, now is 0~854 */
#define UVCHAM_AFMODE              0x00000022    /* auto focus mode (0:manul focus; 1:auto focus; 2:once focus; 3:Conjugate calibration) */
#define UVCHAM_AFZONE              0x00000023    /* auto focus zone index
                                                    the whole resolution is divided in w * h zones:
                                                        w = max & 0xff
                                                        h = (max >> 8) & 0xff
                                                    then:
                                                        zone row:    value / w
                                                        zone column: value % w
                                                 */
#define UVCHAM_AFFEEDBACK          0x00000024    /* auto focus information feedback
                                                    0: unknown
                                                    1: focused
                                                    2: focusing
                                                    3: defocuse (out of focus)
                                                    4: up (workbench move up)
                                                    5: down (workbench move down)
                                                 */
#define UVCHAM_AFPOSITION_ABSOLUTE 0x00000025    /* absolute auto focus sensor board positon: -5400um~10600um(-5.4mm~10.6mm) */
#define UVCHAM_PAUSE               0x00000026    /* pause */
#define UVCHAM_SN                  0x00000027    /* serial number */
#define UVCHAM_BPS                 0x00000032    /* bitrate: Mbps */
#define UVCHAM_LIGHT_ADJUSTMENT    0x00000033    /* light source brightness adjustment */
#define UVCHAM_ZOOM                0x00000034    /* SET only */
#define UVCHAM_USER                0x00000035    /* User */
#define UVCHAM_EF_MODE             0x00000036
#define UVCHAM_EF_FL               0x00000037
#define UVCHAM_EF_APERTURE_MIN_MAX 0x00000038
#define UVCHAM_EF_APERTURE_CUR     0x00000039
#define UVCHAM_EF_FOCUS_CUR        0x0000003a
#define UVCHAM_EF_FOCUS_MAX        0x0000003b
#define UVCHAM_EF_LENS_ID          0x0000003c
#define UVCHAM_EF_AFMF             0x0000003d
#define UVCHAM_EF_WD_ENABLE        0x0000003e
#define UVCHAM_EF_WD_NEAR          0x0000003f
#define UVCHAM_EF_WD_FAR           0x00000040
#define UVCHAM_TEMP                0x00000042    /* temp/tint mode: color temperature */
#define UVCHAM_TINT                0x00000043    /* temp/tint mode: tint */
#define UVCHAM_AGAIN               0x00000084    /* analog gain */
#define UVCHAM_NEGATIVE            0x00000085    /* negative film */
#define UVCHAM_REALTIME            0x00000086    /* realtime: 1 => ON, 0 => OFF */
#define UVCHAM_FORMAT              0x000000fe    /* output format: 0 => BGR888, 1 => BGRA8888, 2 => RGB888, 3 => RGBA8888; default: 0
                                                    Can be changed only when camera is not running.
                                                 */
#define UVCHAM_CODEC               0x01000000    /* codec:
                                                    Can be changed only when camera is not running.
                                                    To get the number of the supported codec, use: Uvcham_range(h, UVCHAM_CODEC, nullptr, &num, nullptr)
                                                 */
#define UVCHAM_CODEC_FOURCC        0x02000000    /* to get fourcc of the nth codec, use: Uvcham_get(h, UVCHAM_CODEC_FOURCC | n, &fourcc), such as MAKEFOURCC('M', 'J', 'P', 'G') */
#define UVCHAM_RES                 0x10000000    /* resolution:
                                                    Can be changed only when camera is not running.
                                                    To get the number of the supported resolution, use: Uvcham_range(h, UVCHAM_RES, nullptr, &num, nullptr)
                                                 */
#define UVCHAM_WIDTH               0x40000000    /* to get the nth width, use: Uvcham_get(h, UVCHAM_WIDTH | n, &width) */
#define UVCHAM_HEIGHT              0x80000000

/********************************************************************/
/* How to enum the resolutions:                                     */
/*     Uvcham_range(h, UVCHAM_RES, nullptr, &num, nullptr);         */
/*     for (int i = 0; i <= num; ++i)                               */
/*     {                                                            */
/*         int width, height;                                       */
/*         Uvcham_get(h, UVCHAM_WIDTH | i, &width);                 */
/*         Uvcham_get(h, UVCHAM_HEIGHT | i, &height);               */
/*         printf("%d: %d x %d\n", i, width, height);               */
/*     }                                                            */
/********************************************************************/

/********************************************************************/
/* "Direct Mode" vs "Pull Mode"                                     */
/* (1) Direct Mode:                                                 */
/*     (a) Uvcham_start(h, pFrameBuffer, ...)                       */
/*     (b) pros: simple, slightly more efficient                    */
/* (2) Pull Mode:                                                   */
/*     (a) Uvcham_start(h, nullptr, ...)                            */
/*     (b) use Uvcham_pull(h, pFrameBuffer) to pull image           */
/*     (c) pros: never frame confusion                              */
/********************************************************************/

/********************************************************************/
/* How to test whether the camera supports auto focus:              */
/*     if (SUCCEEDED(Uvcham_get(h, UVCHAM_AFZONE, &val))            */
/*         // yes, it supports                                      */
/*     else                                                         */
/*         // not supported                                         */
/********************************************************************/

/* event */
#define UVCHAM_EVENT_IMAGE         0x0001
#define UVCHAM_EVENT_DISCONNECT    0x0002    /* camera disconnect */
#define UVCHAM_EVENT_ERROR         0x0004    /* error */

#define UVCHAM_WBROI_WIDTH_MIN     48
#define UVCHAM_WBROI_HEIGHT_MIN    32

#if defined(_WIN32) && !defined(UVCHAM_DSHOW) && !defined(UVCHAM_TWAIN)
#ifdef UVCHAM_EXPORTS
#define UVCHAM_API(x)    __declspec(dllexport)   x   __stdcall  /* in Windows, we use __stdcall calling convention, see https://docs.microsoft.com/en-us/cpp/cpp/stdcall */
#else
#define UVCHAM_API(x)    __declspec(dllimport)   x   __stdcall
#endif

#ifndef TDIBWIDTHBYTES
#define TDIBWIDTHBYTES(bits)  ((unsigned)(((bits) + 31) & (~31)) / 8)
#endif

/* handle */
typedef struct UvchamT { int unused; } *HUvcham;

/* sdk version */
UVCHAM_API(const wchar_t*)   Uvcham_version();

typedef struct {
    wchar_t   displayname[128];    /* display name */
    wchar_t   id[128];             /* unique and opaque id of a connected camera, for Uvcham_open */
} UvchamDevice; /* camera for enumerating */

/*
    enumerate the cameras connected to the computer, return the number of enumerated.
*/
UVCHAM_API(unsigned) Uvcham_enum(UvchamDevice arr[UVCHAM_MAX]);

/* camId == nullptr means the first device to open */
UVCHAM_API(HUvcham) Uvcham_open(const wchar_t* camId);

typedef void (__stdcall* PUVCHAM_CALLBACK)(unsigned nEvent, void* pCallbackCtx);
/* pFrameBuffer must be >= WIDTHBYTES(width * 24) * height */
UVCHAM_API(HRESULT) Uvcham_start(HUvcham h, void* pFrameBuffer, PUVCHAM_CALLBACK pCallbackFun, void* pCallbackCtx);
UVCHAM_API(HRESULT) Uvcham_stop(HUvcham h);
UVCHAM_API(void) Uvcham_close(HUvcham h);

/*
    nId: UVCHAM_XXXX
*/
UVCHAM_API(HRESULT) Uvcham_put(HUvcham h, unsigned nId, int val);
UVCHAM_API(HRESULT) Uvcham_get(HUvcham h, unsigned nId, int* pVal);
UVCHAM_API(HRESULT) Uvcham_range(HUvcham h, unsigned nId, int* pMin, int* pMax, int* pDef);

UVCHAM_API(HRESULT) Uvcham_pull(HUvcham h, void* pFrameBuffer);

/* filePath == NULL means to stop record.
   support file extension: *.asf, *.mp4, *.mkv
*/
UVCHAM_API(HRESULT) Uvcham_record(HUvcham h, const char* filePath);

#endif
#ifdef __cplusplus
}
#endif
#endif
