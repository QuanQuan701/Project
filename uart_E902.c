/******************************************************************************
 * @file    main.c
 * @brief   UART Protocol Implementation for T-Head E902
 * @version V2.0 (Ported from Xilinx XUartLite)
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "drv_usart.h"
#include "soc.h"
// #include "pin.h"  // 如果需要配置引脚复用，请取消注释并确保头文件存在

/************************** Constant Definitions *****************************/

#define EXAMPLE_USART_IDX  0       // UART0
#define FRAME_HEADER       0x02    // STX
#define FRAME_TAIL         0x03    // ETX
#define FRAME_LENGTH       12      // 帧长度12 字节
#define CMD_READ           0x52    // 'R'
#define CMD_VERSION        0x56    // 'V'
#define CMD_WRITE          0x57    // 'W'
#define RECV_BUFFER_SIZE   32
#define TIMEOUT_THRESHOLD  10000   // 超时计数阈值

#define FW_VERSION_MAJOR   2
#define FW_VERSION_MINOR   1
#define FW_VERSION_PATCH   0
#define FW_VERSION_CODE    (((uint32_t)FW_VERSION_MAJOR << 16) | ((uint32_t)FW_VERSION_MINOR << 8) | (uint32_t)FW_VERSION_PATCH)

// FPGA 寄存器读写宏（直接访问硬件绝对地址）
#define REG32(addr) (*((volatile uint32_t *)(addr)))
// 调试开关：设置为 1 启用调试输出，0 关闭
#define DEBUG_PROTOCOL     0

/************************** Variable Definitions *****************************/

static usart_handle_t g_uart_handle;

/************************** Function Prototypes ******************************/

void Platform_Uart_Init(int32_t uart_idx);
void Platform_Pin_Init(void);  // 引脚初始化（根据实际硬件配置）
int  Platform_Uart_ReceiveByte(uint8_t *ch);
int Platform_Uart_SendBuf(uint8_t *buf, uint32_t len);

uint8_t CalculateChecksum(uint8_t *data, int len);
uint32_t GetFpgaRegister(uint32_t addr);
void SetFpgaRegister(uint32_t addr, uint32_t data);
void ISP_BatchConfig(void);
void UartProcTask(void);

/************************** Main Entry ***************************************/

int main(void)
{
    // 1. 初始化引脚复用（根据硬件平台配置）
    Platform_Pin_Init();
    
    // 2. 初始化 E902 串口驱动
    Platform_Uart_Init(EXAMPLE_USART_IDX);

    printf("BOOT: Platform_Uart_Init success\r\n");
    printf("BOOT: E902 UART Protocol Task Started\r\n");
    printf("FW_VERSION:%d.%d.%d\r\n", FW_VERSION_MAJOR, FW_VERSION_MINOR, FW_VERSION_PATCH);

    // 3. 主循环：轮询协议任务
    while (1) {
        UartProcTask();
    }

    return 0;
}

/************************** E902 Platform HAL ********************************/

/**
 * @brief 初始化 UART 引脚复用（根据具体硬件平台配置）
 * 注意：需要根据实际使用的 UART 和引脚配置修改
 */
void Platform_Pin_Init(void)
{
    // 示例配置，需要根据实际硬件替换为正确的引脚和功能
    // drv_pinmux_config(EXAMPLE_PIN_USART_TX, EXAMPLE_PIN_USART_TX_FUNC);
    // drv_pinmux_config(EXAMPLE_PIN_USART_RX, EXAMPLE_PIN_USART_RX_FUNC);
    
    // TODO: 根据您的硬件平台配置正确的引脚复用
    // 如果引脚已由 BSP 或 bootloader 配置，可以留空此函数
}

/**
 * @brief 初始化 E902 串口 (替换 XUartLite_Initialize)
 */
void Platform_Uart_Init(int32_t uart_idx)
{
    int32_t  ret;
    
    // CSI 驱动初始化
    g_uart_handle = csi_usart_initialize(uart_idx, NULL);
    if (g_uart_handle == NULL) {
        printf("Platform_Uart_Init: initialize fail\r\n");
        return;
    }
    
    // 配置协议: 115200, 8N1 (对应 Xilinx 默认配置)
    ret = csi_usart_config(g_uart_handle, 115200, 
                     USART_MODE_ASYNCHRONOUS, 
                     USART_PARITY_NONE, 
                     USART_STOP_BITS_1, 
                     USART_DATA_BITS_8);
    if (ret < 0) {
        printf("Platform_Uart_Init: config fail (ret=%d)\r\n", ret);
        return;
    }
    
    // 关键修复：禁用中断，避免ISR消费FIFO数据
    // csi_usart_initialize默认会启用RX/TX中断，必须显式禁用
    csi_usart_set_interrupt(g_uart_handle, USART_INTR_READ, 0);  // 禁用接收中断
    csi_usart_set_interrupt(g_uart_handle, USART_INTR_WRITE, 0); // 禁用发送中断
    
    // 清空接收缓冲区，移除初始化时的垃圾数据
    csi_usart_flush(g_uart_handle, USART_FLUSH_READ);
    
    printf("Platform_Uart_Init: success (115200-8N1, polling mode)\r\n");
}

/**
 * @brief 非阻塞接收一个字节 (替换 XUartLite_Recv)
 * @return 1 表示成功接收1字节，0表示无数据
 */
int Platform_Uart_ReceiveByte(uint8_t *ch)
{
    if(csi_usart_getchar_nonblocking(g_uart_handle, ch) == 0) {
        return 1;  // 成功接收一个字节
    }
    return 0;  // 无数据
}

/**
 * @brief 同步发送缓冲区 (替换 XUartLite_Send)
 * @return 0表示发送成功，-1表示失败
 */
int Platform_Uart_SendBuf(uint8_t *buf, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        if (csi_usart_putchar(g_uart_handle, buf[i]) != 0) {
            // 发送失败处理
            return -1;
        }
    }
    return 0;  // 发送成功
}

/************************** Helper Functions *********************************/

uint8_t CalculateChecksum(uint8_t *data, int len)
{
    uint32_t sum = 0;
    for (int i = 0; i < len; i++) {
        sum += data[i];
    }
    return (uint8_t)(sum & 0xFF);
}

uint32_t GetFpgaRegister(uint32_t addr)
{
    // 直接使用 32-bit 绝对地址访问
    return REG32(addr);
}

void SetFpgaRegister(uint32_t addr, uint32_t data)
{
    // 直接使用 32-bit 绝对地址访问
    REG32(addr) = data;
}
/************************** Protocol State Machine ***************************/

/**
 * @brief UART 协议处理任务 - 轮询模式状态机
 * 帧格式 (12 bytes): Header(0x02) + Cmd(1) + Addr(4) + Data(4) + Checksum(1) + Tail(0x03)
 */
void UartProcTask(void)
{
    static int task = 0;
    static int rx_len = 0;
    static uint8_t rb[RECV_BUFFER_SIZE];
    static uint8_t sb[FRAME_LENGTH];
    static uint32_t timeout_cnt = 0;
    
    uint8_t byte_in;
    uint32_t addr, data;

    switch (task) {
        case 0: // 状态 0: 等待包头 (0x02)
            if (Platform_Uart_ReceiveByte(&byte_in) == 1) {
                if (byte_in == FRAME_HEADER) {
                    rb[0] = byte_in;
                    rx_len = 1;
                    task = 10;
                }
            }
            break;

        case 10: // 状态 10: 接收中间 10 字节 (Cmd + Addr + Data + Checksum)
            // csi_usart_getchar是阻塞的，一次接收一个字节
            if (rx_len < 11) {
                if (Platform_Uart_ReceiveByte(&byte_in) == 1) {
                    rb[rx_len++] = byte_in;
                    timeout_cnt = 0; // Reset timeout counter on successful receive
                } else {
                    timeout_cnt++;
                    if (timeout_cnt > TIMEOUT_THRESHOLD) {
                        task = 0; // Timeout, reset state machine
                    }
                }
            }
            
            if (rx_len == 11) {
                task = 20; // 满 11 字节后跳转等待帧尾
            }
            break;

        case 20: // 状态 20: 检查帧尾 (0x03)
            if (Platform_Uart_ReceiveByte(&byte_in) == 1) {
                rb[11] = byte_in;
                if (rb[11] == FRAME_TAIL) {
                    task = 30; // 帧尾正确，进行校验
                } else {
                    task = 0;  // 帧尾错误，重置
                }
            }
            break;

        case 30: // 状态 30: 校验计算
            if (CalculateChecksum(rb, 10) == rb[10]) {
                task = 40; // 校验成功，进入业务逻辑
            } else {
                task = 0;  // 校验失败，重新开始
            }
            break;

        case 40: // 状态 40: 业务解析
            {
                uint8_t cmd = rb[1];
                
                // 解析地址 (大端序转换)
                addr = ((uint32_t)rb[2] << 24) | ((uint32_t)rb[3] << 16) | 
                       ((uint32_t)rb[4] << 8)  | (uint32_t)rb[5];
                
                // 解析数据 (大端序转换)
                data = ((uint32_t)rb[6] << 24) | ((uint32_t)rb[7] << 16) | 
                       ((uint32_t)rb[8] << 8)  | (uint32_t)rb[9];

                if (cmd == CMD_READ) {
                    data = GetFpgaRegister(addr);
                } else if (cmd == CMD_VERSION) {
                    addr = 0;
                    data = FW_VERSION_CODE;
                } else if (cmd == CMD_WRITE) {
                    SetFpgaRegister(addr, data);
                }

                // 准备回传帧
                sb[0] = FRAME_HEADER;
                sb[1] = cmd;
                sb[2] = (uint8_t)(addr >> 24); 
                sb[3] = (uint8_t)(addr >> 16);
                sb[4] = (uint8_t)(addr >> 8);  
                sb[5] = (uint8_t)addr;
                sb[6] = (uint8_t)(data >> 24); 
                sb[7] = (uint8_t)(data >> 16);
                sb[8] = (uint8_t)(data >> 8);  
                sb[9] = (uint8_t)data;
                sb[10] = CalculateChecksum(sb, 10);
                sb[11] = FRAME_TAIL;

                task = 50; 
            }
            break;

        case 50: // 状态 50: 发送回复包
            Platform_Uart_SendBuf(sb, FRAME_LENGTH);
            task = 0; // 完成后回到等待状态
            break;

        default:
            task = 0;
            break;
    }
}