/*
 * DDS140 の USB プロトコルを実機で確かめるための最小ハーネス（32bit, Windows）。
 *
 * ベンダ GUI を使わず、USBInterFace.dll（本物）を直接叩いて
 *   - 制御コマンドの応答
 *   - 波形データの取得（EP 0x82）と中身
 * を記録する。結果をそのまま macOS 実装に写す。
 *
 * ビルド: i686-w64-mingw32-gcc -O2 -o probe.exe probe.c -static
 * 実行:   probe.exe            （DDS140 フォルダで、DLL の隣に置く）
 *
 * 読み取り専用。設定コマンドはベンダ GUI と同じ値しか送らない。
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

typedef int   (__stdcall *fn_i_v)(void);
typedef int   (__stdcall *fn_ai)(int, unsigned int, int, void *);
typedef unsigned char (__stdcall *fn_cmd)(unsigned char, unsigned short, unsigned int);
typedef int   (__stdcall *fn_cmds)(int);
typedef void *(__stdcall *fn_ptr)(int);
typedef void  (__stdcall *fn_setinfo)(double, double, unsigned char, int, unsigned int, unsigned int);
typedef void  (__stdcall *fn_u)(unsigned int);

static fn_i_v        pDeviceOpen, pDeviceClose;
static fn_ai         pAiReadBulkData;
static fn_cmd        pUSBCtrlTrans;
static fn_cmds       pUSBCtrlTransSimple;
static fn_ptr        pGetBuffer4Wr;
static fn_setinfo    pSetInfo;
static fn_u          pSetReadEnableOrNot;

#define SYM(name) p##name = (void *)GetProcAddress(h, #name); \
    if (!p##name) { printf("missing export: %s\n", #name); return 2; }

static unsigned char cmd(unsigned char req, unsigned short val)
{
    unsigned char r = pUSBCtrlTrans(req, val, 1);
    printf("  cmd(%3u, %5u/0x%04x) -> 0x%02x (%u)\n", req, val, val, r, r);
    return r;
}

static int cmd_simple(int req)
{
    int r = pUSBCtrlTransSimple(req);
    printf("  cmdSimple(%3d) -> %d\n", req, r);
    return r;
}

static double stat_byte(const unsigned char *p, int n, int stride, int off)
{
    int i, cnt = 0, mn = 255, mx = 0;
    double sum = 0;
    for (i = off; i < n; i += stride) {
        int v = p[i];
        if (v < mn) mn = v;
        if (v > mx) mx = v;
        sum += v;
        cnt++;
    }
    printf("    stride %d off %d: n=%d min=%d max=%d avg=%.2f\n", stride, off, cnt, mn, mx,
           cnt ? sum / cnt : 0.0);
    return cnt ? sum / cnt : 0;
}

static void dump(const char *name, const unsigned char *p, int n)
{
    FILE *f = fopen(name, "wb");
    if (f) { fwrite(p, 1, n, f); fclose(f); printf("    wrote %s (%d bytes)\n", name, n); }
}

/* 1 フレーム取る。readCount バイトを EP0x82 から chunks 回に分けて読む。 */
static int grab(const char *tag, int readCount, unsigned int chunks)
{
    unsigned char *buf = (unsigned char *)pGetBuffer4Wr(-1);
    int i, st = -1;
    char name[128];

    printf("[%s] readCount=%d chunks=%u chunkBytes=%d\n", tag, readCount, chunks,
           chunks ? readCount / (int)chunks : 0);
    if (!buf) { printf("  GetBuffer4Wr -> NULL\n"); return -1; }
    memset(buf, 0xAA, readCount);

    pSetReadEnableOrNot(1);
    cmd_simple(51);
    for (i = 0; i < 40; i++) {
        st = cmd_simple(80);
        if (st == 33) break;
        Sleep(20);
    }
    printf("  status after %d polls: %d\n", i + 1, st);
    if (st != 33) {
        printf("  -> not ready, abort frame\n");
        return -1;
    }
    {
        int r = pAiReadBulkData(readCount, chunks, 20000, buf);
        printf("  AiReadBulkData -> %d (async: 完了を待つ)\n", r);
        Sleep(250);
    }
    stat_byte(buf, readCount, 2, 0);
    stat_byte(buf, readCount, 2, 1);
    printf("    head: ");
    for (i = 0; i < 32; i++) printf("%02x", buf[i]);
    printf("\n");
    sprintf(name, "capture_%s.bin", tag);
    dump(name, buf, readCount);
    return 0;
}

int main(void)
{
    HMODULE h = LoadLibraryA("USBInterFace_real.dll");
    int i;

    if (!h) {
        printf("LoadLibrary(USBInterFace_real.dll) failed: %lu\n", GetLastError());
        return 2;
    }
    SYM(DeviceOpen); SYM(DeviceClose); SYM(AiReadBulkData); SYM(USBCtrlTrans);
    SYM(USBCtrlTransSimple); SYM(GetBuffer4Wr); SYM(SetInfo); SYM(SetReadEnableOrNot);

    printf("DeviceOpen -> %d\n", pDeviceOpen());

    printf("--- calibration (cmd 144)\n");
    for (i = 1; i <= 19; i++) cmd(144, (unsigned short)i);

    printf("--- config\n");
    /* ベンダ GUI の初期値: CH1/CH2 とも 1V/div、DC、2ch、100MS/s */
    cmd(36, 0x00);     /* CtrlByte1: 結合なし・両CH 1V 域 */
    cmd(148, 0x00);    /* CtrlByte0: 100MS/s(2ch) / DC */
    cmd(34, 0);        /* CH1 レンジ */
    cmd(35, 0);        /* CH2 レンジ */
    cmd(231, 0);       /* トリガ源 = CH1 */
    pSetInfo(0.4, 100000.0, 0x11, 128, 0, 131072);
    pSetReadEnableOrNot(1);

    Sleep(200);
    grab("2ch_100M", 131072, 4);
    Sleep(200);
    grab("2ch_100M_b", 131072, 4);

    printf("--- switch to 10MS/s\n");
    cmd(148, 0x0C);
    Sleep(300);
    grab("2ch_10M", 131072, 4);

    printf("--- switch to 625kS/s\n");
    cmd(148, 0x08);
    Sleep(300);
    grab("2ch_625k", 131072, 4);

    printf("DeviceClose -> %d\n", pDeviceClose());
    return 0;
}
