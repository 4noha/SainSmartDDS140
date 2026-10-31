/*
 * USBInterFace.dll を差し替えて、ベンダ GUI が実際に送っている USB コマンドを
 * 記録するためのプロキシ（32bit, stdcall）。
 *
 * 使い方（Windows 側）:
 *   USBInterFace.dll      -> USBInterFace_real.dll にリネーム
 *   この DLL を USBInterFace.dll として置く
 *   DDS140.exe を起動（ログは CWD の usb_proxy.log と usb_proxy_N.bin）
 *
 * 失敗したら USBInterFace.dll を消して、_real を元に戻すだけ。
 */
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

#define REAL_DLL_NAME "USBInterFace_real.dll"

static HMODULE g_real = NULL;
static FILE *g_log = NULL;
static int g_bin_dump_count = 0;
static int g_ai_calls = 0;

static void log_init(void)
{
    if (!g_log) {
        g_log = fopen("usb_proxy.log", "w");
    }
}

static void LOG(const char *fmt, ...)
{
    va_list ap;
    log_init();
    if (!g_log) return;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

static void load_real(void)
{
    char path[MAX_PATH];
    if (g_real) return;
    GetModuleFileNameA(NULL, path, MAX_PATH);
    {
        char *slash = strrchr(path, '\\');
        if (slash) *(slash + 1) = '\0';
    }
    strcat(path, REAL_DLL_NAME);
    g_real = LoadLibraryA(path);
    if (!g_real) {
        /* フォールバック: カレントディレクトリ */
        g_real = LoadLibraryA(REAL_DLL_NAME);
    }
    LOG("proxy: real dll = %s", g_real ? path : "(FAILED)");
}

static FARPROC sym(const char *name)
{
    FARPROC p;
    load_real();
    if (!g_real) return NULL;
    p = GetProcAddress(g_real, name);
    if (!p) LOG("proxy: missing export %s", name);
    return p;
}

/* ---- 型 ---- */
typedef int   (__stdcall *fn_i_v)(void);
typedef int   (__stdcall *fn_i_i)(int);
typedef int   (__stdcall *fn_ai)(int, unsigned int, int, void *);
typedef unsigned char (__stdcall *fn_cmd)(unsigned char, unsigned short, unsigned int);
typedef int   (__stdcall *fn_cmds)(int);
typedef int   (__stdcall *fn_dpd)(unsigned int, unsigned int, unsigned int);
typedef int   (__stdcall *fn_trig)(unsigned char, unsigned char);
typedef void *( __stdcall *fn_ptr)(int);
typedef int   (__stdcall *fn_reset)(void);
typedef void  (__stdcall *fn_setinfo)(double, double, unsigned char, int, unsigned int, unsigned int);
typedef double(__stdcall *fn_getd)(int);
typedef void  (__stdcall *fn_setd)(int, double);
typedef void  (__stdcall *fn_settrig)(unsigned char, unsigned char, unsigned char);
typedef void  (__stdcall *fn_u)(unsigned int);
typedef unsigned int (__stdcall *fn_u_v)(void);
typedef unsigned char (__stdcall *fn_c_i)(int);
typedef double(__stdcall *fn_d_i)(int);

__declspec(dllexport) int __stdcall DeviceOpen(void)
{
    fn_i_v f = (fn_i_v)sym("DeviceOpen");
    int r = f ? f() : -1;
    LOG("DeviceOpen() -> %d", r);
    return r;
}

__declspec(dllexport) int __stdcall DeviceClose(void)
{
    fn_i_v f = (fn_i_v)sym("DeviceClose");
    int r = f ? f() : -1;
    LOG("DeviceClose() -> %d", r);
    return r;
}

__declspec(dllexport) int __stdcall AiReadBulkData(int sampleCount, unsigned int num, int timeout, void *buf)
{
    fn_ai f = (fn_ai)sym("AiReadBulkData");
    LARGE_INTEGER t0, t1, freq;
    int r;
    QueryPerformanceCounter(&t0);
    r = f ? f(sampleCount, num, timeout, buf) : -1;
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&freq);
    {
        double ms = (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / (double)freq.QuadPart;
        unsigned int chunk = num ? (unsigned int)sampleCount / num : 0;
        unsigned char *p = (unsigned char *)buf;
        g_ai_calls++;
        if (p) {
            LOG("AiReadBulkData(%d, %u, %d) -> %d  [chunk=%u, %.1fms] head=%02x%02x%02x%02x %02x%02x%02x%02x",
                sampleCount, num, timeout, r, chunk, ms,
                p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]);
        } else {
            LOG("AiReadBulkData(%d, %u, %d) -> %d  [buf=NULL]", sampleCount, num, timeout, r);
        }
        if (p && sampleCount > 0 && g_bin_dump_count < 8) {
            char name[64];
            sprintf(name, "usb_proxy_%d.bin", g_bin_dump_count);
            {
                FILE *bf = fopen(name, "wb");
                if (bf) {
                    fwrite(p, 1, (size_t)(sampleCount > 0 ? sampleCount : 0), bf);
                    fclose(bf);
                    LOG("  dumped %d bytes -> %s", sampleCount, name);
                }
            }
            g_bin_dump_count++;
        }
    }
    return r;
}

__declspec(dllexport) int __stdcall EventCheck(int timeout)
{
    fn_i_i f = (fn_i_i)sym("EventCheck");
    return f ? f(timeout) : -1;
}

__declspec(dllexport) unsigned char __stdcall USBCtrlTrans(unsigned char request, unsigned short value, unsigned int outBufSize)
{
    fn_cmd f = (fn_cmd)sym("USBCtrlTrans");
    unsigned char r = f ? f(request, value, outBufSize) : 0;
    LOG("cmd(%3u, 0x%04x) -> 0x%02x", request, value, r);
    return r;
}

__declspec(dllexport) int __stdcall USBCtrlTransSimple(int request)
{
    fn_cmds f = (fn_cmds)sym("USBCtrlTransSimple");
    int r = f ? f(request) : -1;
    LOG("cmdSimple(%d) -> %d", request, r);
    return r;
}

__declspec(dllexport) int __stdcall DataPreDisposal(unsigned int type, unsigned int start, unsigned int count)
{
    fn_dpd f = (fn_dpd)sym("DataPreDisposal");
    return f ? f(type, start, count) : 0;
}

__declspec(dllexport) int __stdcall TrigDataPrepare(unsigned char l0, unsigned char l1)
{
    fn_trig f = (fn_trig)sym("TrigDataPrepare");
    return f ? f(l0, l1) : -1;
}

__declspec(dllexport) void * __stdcall GetBuffer4Read(int index)
{
    fn_ptr f = (fn_ptr)sym("GetBuffer4Read");
    return f ? f(index) : NULL;
}

__declspec(dllexport) void * __stdcall GetBuffer4Wr(int index)
{
    fn_ptr f = (fn_ptr)sym("GetBuffer4Wr");
    return f ? f(index) : NULL;
}

__declspec(dllexport) void * __stdcall GetRawData4Read(int index)
{
    fn_ptr f = (fn_ptr)sym("GetRawData4Read");
    return f ? f(index) : NULL;
}

__declspec(dllexport) int __stdcall ResetPipe(void)
{
    fn_reset f = (fn_reset)sym("ResetPipe");
    int r = f ? f() : 0;
    LOG("ResetPipe() -> %d", r);
    return r;
}

__declspec(dllexport) void __stdcall SetInfo(double dataNumPerPixar, double currentSampleRate,
                                            unsigned char channelMask, int zeroUni,
                                            unsigned int bufferOffset, unsigned int hwBufferSize)
{
    fn_setinfo f = (fn_setinfo)sym("SetInfo");
    LOG("SetInfo(num/pix=%g, rate=%g, mask=0x%02x, zero=%d, ofs=%u, size=%u)",
        dataNumPerPixar, currentSampleRate, channelMask, zeroUni, bufferOffset, hwBufferSize);
    if (f) f(dataNumPerPixar, currentSampleRate, channelMask, zeroUni, bufferOffset, hwBufferSize);
}

__declspec(dllexport) double __stdcall GetData(int index)
{
    fn_getd f = (fn_getd)sym("GetData");
    return f ? f(index) : 0.0;
}

__declspec(dllexport) void __stdcall SetData(int index, double value)
{
    fn_setd f = (fn_setd)sym("SetData");
    if (f) f(index, value);
}

__declspec(dllexport) void __stdcall SetTrigInfo(unsigned char src, unsigned char mode, unsigned char edge)
{
    fn_settrig f = (fn_settrig)sym("SetTrigInfo");
    LOG("SetTrigInfo(src=%u, mode=%u, edge=%u)", src, mode, edge);
    if (f) f(src, mode, edge);
}

__declspec(dllexport) void __stdcall BufferInit(void)
{
    fn_i_v f = (fn_i_v)sym("BufferInit");
    if (f) f();
}

__declspec(dllexport) void __stdcall SetReadEnableOrNot(unsigned int en)
{
    fn_u f = (fn_u)sym("SetReadEnableOrNot");
    if (f) f(en);
}

__declspec(dllexport) void __stdcall SetStableEnableOrNot(unsigned int en)
{
    fn_u f = (fn_u)sym("SetStableEnableOrNot");
    LOG("SetStableEnableOrNot(%u)", en);
    if (f) f(en);
}

__declspec(dllexport) unsigned int __stdcall GetHWbufferSize(void)
{
    fn_u_v f = (fn_u_v)sym("GetHWbufferSize");
    return f ? f() : 0;
}

__declspec(dllexport) unsigned char __stdcall GetInfoByte(int i)
{
    fn_c_i f = (fn_c_i)sym("GetInfoByte");
    return f ? f(i) : 0;
}

__declspec(dllexport) double __stdcall GetInfodouble(int i)
{
    fn_d_i f = (fn_d_i)sym("GetInfodouble");
    return f ? f(i) : 0.0;
}

__declspec(dllexport) void __stdcall AutoMeasurement(int ch)
{
    fn_i_i f = (fn_i_i)sym("AutoMeasurement");
    if (f) f(ch);
}

BOOL __stdcall DllMain(HMODULE h, DWORD reason, LPVOID reserved)
{
    (void)h; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        LOG("proxy: attached (pid %lu)", (unsigned long)GetCurrentProcessId());
    }
    return TRUE;
}
