/******************************************************************************
 * @file     main.c
 * @brief    app
 * @version  V1.0
 * @date     13. May 2023
 ******************************************************************************/

#include <stdio.h>
#include <time.h>
#include <stdint.h>

#include "core_rv32.h"

#include "soc.h"
#include "drv_gpio.h"
#include "dw_gpio.h"
#include "pin_name.h"
#include "pin.h"
#include "drv_usart.h"
#include "drv_pwm.h"
#include "drv_timer.h"
#include "drv_wdt.h"

#include "myReg.h"
#include "iap.h"

#include "dw_timer.h"

#include "myXmodem.h"

#include "console.h"

#include "spi_flash.h"
//#include "watch_dog.h"
//#include "apb_reg_test.h"
#include "dw_pwm.h"
#include "pinmux.h"
#include "my_gpioTest.h"

//#include "my_print.h"

#include "tgd25q.h"
#include "dw_apb_iic.h"
#include "dw_apb_spi.h"

#include "i2c_app.h"

#include "read_write_func.h"
#include "isp_config.h"
#include "mipi_config.h"
#include "mac_config.h"

#include "gc2093.h"

#include "mdio.h"

#define WORK_MODE_NORMAL                     0
#define WORK_MODE_TEST_GPIO                  0  // vu9p_240603 test ok
#define WORK_MODE_TEST_IIC_FOR_EEPROM        0  // test ok
                                                // k410t_core2_stereo_240904_1, M2 test ok
#define WORK_MODE_TEST_SPI                   0  // vu9p_240603 test ok
                                                // k410t_core2_stereo_240904_1 test ok
#define WORK_MODE_TEST_WDT                   0  // vu9p_240603 test ok
#define WORK_MODE_TEST_PWM                   0  // test ok
#define WORK_MODE_TEST_PADMUX                0  // test ok
#define WORK_MODE_TEST_TIMER                 0  // test ok
#define WORK_MODE_TEST_CPU_CORE              0
#define WORK_MODE_TEST_INTERRUPT             0  // PA28 int ok
#define WORK_MODE_TEST_IAP                   0  // test ok
#define WORK_MODE_TEST_READ_ROM              0  // ok
#define WORK_MODE_TEST_READ_SPI_ROMCODE      0  // ok
#define WORK_MODE_TEST_ONLY_PRINT            0  // ok
#define WORK_MODE_TEST_XMODEM                0  // vu9p_240603 test ok
#define WORK_MODE_TEST_UART                  0  // ok
#define WORK_MODE_TEST_UART_PROTOCOL         1  // UART寄存器协议
#define WORK_MODE_TEST_CGU                   0

#define WORK_MODE_TEST_IIC_FOR_GC2093_DVP    0  // k410t_core2_stereo_240904_1 test ok

#define WORK_MODE_TEST_Auto_Exposure_GC2093_DVP    0  // VU19P Auto-Exposure of GC2093-DVP



extern void (*g_irqvector[])(void);

gpio_pin_handle_t PA0_pin_handle = NULL;
gpio_pin_handle_t PA1_pin_handle = NULL;
gpio_pin_handle_t PA2_pin_handle = NULL;
gpio_pin_handle_t PA3_pin_handle = NULL;
gpio_pin_handle_t PA4_pin_handle = NULL;
gpio_pin_handle_t PA5_pin_handle = NULL;
gpio_pin_handle_t PA6_pin_handle = NULL;
gpio_pin_handle_t PA7_pin_handle = NULL;
gpio_pin_handle_t PA8_pin_handle = NULL;


#if WORK_MODE_TEST_UART_PROTOCOL
/************************** UART Protocol (Merged from uart_E902.c) *****************************/

#define UART_PROTOCOL_USART_IDX  0       // UART0
#define FRAME_HEADER             0x02    // STX
#define FRAME_TAIL               0x03    // ETX
#define FRAME_LENGTH             12      // 帧长度12字节
#define CMD_READ                 0x52    // 'R'
#define CMD_VERSION              0x56    // 'V'
#define CMD_WRITE                0x57    // 'W'
#define RECV_BUFFER_SIZE         32
#define TIMEOUT_THRESHOLD        10000   // 超时计数阈值

#define FW_VERSION_MAJOR         2
#define FW_VERSION_MINOR         1
#define FW_VERSION_PATCH         0
#define FW_VERSION_CODE          (((uint32_t)FW_VERSION_MAJOR << 16) | ((uint32_t)FW_VERSION_MINOR << 8) | (uint32_t)FW_VERSION_PATCH)

#define REG32(addr)              (*((volatile uint32_t *)(addr)))

static usart_handle_t g_uart_protocol_handle;

static void UartProto_Pin_Init(void)
{
    // 如果硬件已由 bootloader/BSP 配好引脚，这里可留空。
    // 如需手动配置，可在此加入 pinmux 配置。
}

static int UartProto_Init(int32_t uart_idx)
{
    int32_t ret;

    g_uart_protocol_handle = csi_usart_initialize(uart_idx, NULL);
    if (g_uart_protocol_handle == NULL) {
        printf("UartProto_Init: initialize fail\r\n");
        return -1;
    }

    ret = csi_usart_config(g_uart_protocol_handle,
                           115200,
                           USART_MODE_ASYNCHRONOUS,
                           USART_PARITY_NONE,
                           USART_STOP_BITS_1,
                           USART_DATA_BITS_8);
    if (ret < 0) {
        printf("UartProto_Init: config fail (ret=%d)\r\n", ret);
        return -1;
    }

    // 轮询模式：显式关闭RX/TX中断，避免ISR消费FIFO。
    csi_usart_set_interrupt(g_uart_protocol_handle, USART_INTR_READ, 0);
    csi_usart_set_interrupt(g_uart_protocol_handle, USART_INTR_WRITE, 0);
    csi_usart_flush(g_uart_protocol_handle, USART_FLUSH_READ);

    return 0;
}

static int UartProto_ReceiveByte(uint8_t *ch)
{
    if (csi_usart_getchar_nonblocking(g_uart_protocol_handle, ch) == 0) {
        return 1;
    }
    return 0;
}

static int UartProto_SendBuf(const uint8_t *buf, uint32_t len)
{
    uint32_t i;
    for (i = 0; i < len; i++) {
        if (csi_usart_putchar(g_uart_protocol_handle, buf[i]) != 0) {
            return -1;
        }
    }
    return 0;
}

static uint8_t UartProto_Checksum(const uint8_t *data, int len)
{
    uint32_t sum = 0;
    int i;
    for (i = 0; i < len; i++) {
        sum += data[i];
    }
    return (uint8_t)(sum & 0xFF);
}

static uint32_t UartProto_ReadReg(uint32_t addr)
{
    return REG32(addr);
}

static void UartProto_WriteReg(uint32_t addr, uint32_t data)
{
    REG32(addr) = data;
}

static void UartProto_Task(void)
{
    static int task = 0;
    static int rx_len = 0;
    static uint8_t rb[RECV_BUFFER_SIZE];
    static uint8_t sb[FRAME_LENGTH];
    static uint32_t timeout_cnt = 0;

    uint8_t byte_in;
    uint32_t addr, data;

    switch (task) {
    case 0: // 等待包头
        if (UartProto_ReceiveByte(&byte_in) == 1) {
            if (byte_in == FRAME_HEADER) {
                rb[0] = byte_in;
                rx_len = 1;
                timeout_cnt = 0;
                task = 10;
            }
        }
        break;

    case 10: // 接收中间10字节
        if (rx_len < 11) {
            if (UartProto_ReceiveByte(&byte_in) == 1) {
                rb[rx_len++] = byte_in;
                timeout_cnt = 0;
            } else {
                timeout_cnt++;
                if (timeout_cnt > TIMEOUT_THRESHOLD) {
                    task = 0;
                }
            }
        }
        if (rx_len == 11) {
            task = 20;
        }
        break;

    case 20: // 校验帧尾
        if (UartProto_ReceiveByte(&byte_in) == 1) {
            rb[11] = byte_in;
            if (rb[11] == FRAME_TAIL) {
                task = 30;
            } else {
                task = 0;
            }
        }
        break;

    case 30: // 校验和
        if (UartProto_Checksum(rb, 10) == rb[10]) {
            task = 40;
        } else {
            task = 0;
        }
        break;

    case 40: // 执行业务
    {
        uint8_t cmd = rb[1];

        addr = ((uint32_t)rb[2] << 24) |
               ((uint32_t)rb[3] << 16) |
               ((uint32_t)rb[4] << 8) |
               (uint32_t)rb[5];

        data = ((uint32_t)rb[6] << 24) |
               ((uint32_t)rb[7] << 16) |
               ((uint32_t)rb[8] << 8) |
               (uint32_t)rb[9];

        if (cmd == CMD_READ) {
            data = UartProto_ReadReg(addr);
        } else if (cmd == CMD_VERSION) {
            addr = 0;
            data = FW_VERSION_CODE;
        } else if (cmd == CMD_WRITE) {
            UartProto_WriteReg(addr, data);
        }

        sb[0]  = FRAME_HEADER;
        sb[1]  = cmd;
        sb[2]  = (uint8_t)(addr >> 24);
        sb[3]  = (uint8_t)(addr >> 16);
        sb[4]  = (uint8_t)(addr >> 8);
        sb[5]  = (uint8_t)(addr);
        sb[6]  = (uint8_t)(data >> 24);
        sb[7]  = (uint8_t)(data >> 16);
        sb[8]  = (uint8_t)(data >> 8);
        sb[9]  = (uint8_t)(data);
        sb[10] = UartProto_Checksum(sb, 10);
        sb[11] = FRAME_TAIL;

        task = 50;
    }
    break;

    case 50: // 回包
        (void)UartProto_SendBuf(sb, FRAME_LENGTH);
        task = 0;
        break;

    default:
        task = 0;
        break;
    }
}
#endif


#if WORK_MODE_NORMAL
int main(void)
{
    int conf_isp  = 0 ;
    int conf_mipi = 0 ;

    int conf_mac  = 0 ;
    int choose_channel = 0;  //1:mipi 0:dvp
   
    if(choose_channel == 1){
        //mipi
        uint32_t *c_padmux = (__IOM uint32_t *)0x4001C030UL;
        read_param(c_padmux);
        write_param(c_padmux, 0xF000000F);
        read_param(c_padmux);
    }else{
        //dvp
        uint32_t *c_padmux = (__IOM uint32_t *)0x4001C030UL;
        read_param(c_padmux);
        write_param(c_padmux, 0x00000000);
        read_param(c_padmux);
    }
   
    if(conf_isp == 1){
       
        isp_config();
    }
   
    if(conf_mac == 1){

        printf("Ini MAC!\n");
        apb_mac_tx_config();
       
    }
   
    if(conf_mipi == 1){
       
        apb_mipi_tx_raw8_75M_pixclk(); //0x40036000UL
       
//      apb_mipi_raw8_lry_100M(0x40034000UL);
//      apb_mipi_raw8_lry_100M(0x40035000UL);
       
//      apb_mipi_raw8_75M_debug(0x40034000UL) ;
//      apb_mipi_raw8_75M_debug(0x40035000UL) ;

        apb_mipi_raw8_200M_debug(0x40034000UL) ;
        apb_mipi_raw8_200M_debug(0x40035000UL) ;
       
       
//      apb_mipi_raw10_75M_debug(0x40034000UL) ;
//      apb_mipi_raw10_75M_debug(0x40035000UL) ;
//      
//      
//      apb_mipi_raw8_150M(0x40034000UL);
//      apb_mipi_raw8_150M(0x40035000UL);
       
//      apb_mipi1_rx_config_raw8();
        //apb_mipi1_rx_config_raw8_100M();
//      apb_mipi1_rx_config_raw8_lry_100M();
        //apb_mipi1_rx_config_raw10();
       
//      apb_mipi2_rx_config_raw8();
        //apb_mipi2_rx_config_raw8_100M();
//      apb_mipi2_rx_config_raw8_lry_100M();
        //apb_mipi2_rx_config_raw10();
        //apb_mipi3_tx_config();
       
       
       
    }
   
    // //dvp
    // uint32_t *c_padmux_2 = (__IOM uint32_t *)0x4001C030UL;
    // read_param(c_padmux_2);
    // write_param(c_padmux_2, 0x00000000);
    // read_param(c_padmux_2);
    //
    // //mipi
    // uint32_t *c_padmux_3 = (__IOM uint32_t *)0x4001C030UL;
    // read_param(c_padmux_3);
    // write_param(c_padmux_3, 0xF0000000);
    // read_param(c_padmux_3);
   
    while(1);
   
    return 0;
}
#endif

#if WORK_MODE_TEST_GPIO
int main(void)
{
    printf("\r\n TEST GPIO \r\n");

    fvchip_c1_pin_set_Dir(PORTA, PA24,GPIO_DIRECTION_OUTPUT);  // gpio 24 output
    while(1)
    {
        setGpio_Pin_Val(PORTA, PA24, 1);  // light on
        mdelay(200);
       
        setGpio_Pin_Val(PORTA, PA24, 0);  // light off
        mdelay(200);
    }

    return 0;
}
#endif

#if WORK_MODE_TEST_IIC_FOR_EEPROM  // i2c test
//SCL :  VU9P.R22  - FMC.C26 - I2C_SCL1  , input
//SDA :  VU9P.P22  - FMC.C27 - I2C_SDA1  , input
//SCL2:  VU9P.N22  - FMC.D26 - I2C_SCL2  , input
//SDA2:  VU9P.M22  - FMC.D27 - I2C_SDA2  , input
extern void i2c_master_test_write_for_24c02(uint8_t ch, uint8_t devAddr);
extern void i2c_master_test_read_for_24c02(uint8_t ch);
extern void i2c_master_init(uint8_t ch, uint32_t devAddr);
extern void i2c_master_test_case_write_read_100khz(uint8_t ch, uint8_t devAddr);

int main(void)
{
    u8 test_writeBuf[256] = {0};
    u8 test_readBuf[256]={0};
    u32 rdTemp,i;
    u32 val;
    int32_t ret = 0;
   
    printf("\r\n test i2c\r\n");
   
#if 1
    //PC2_SDA_M3               = 0,  PC2_GPIO    = 1,
    //PC3_SCL_M3               = 0,  PC3_GPIO    = 1,
    fvchip_c1_pin_set_mux(PORTC, PC2, PC2_SDA_M3); // PC2_GPIO
    fvchip_c1_pin_set_mux(PORTC, PC3, PC3_SCL_M3); // PC3_GPIO
#endif

#if 1  
    //PC4_SDA_M2               = 0,  PC4_GPIO    = 1,
    //PC5_SCL_M2               = 0,  PC5_GPIO    = 1,
    fvchip_c1_pin_set_mux(PORTC, PC4, PC4_SDA_M2); // PC4_GPIO
    fvchip_c1_pin_set_mux(PORTC, PC5, PC5_SCL_M2); // PC5_GPIO
#endif

#if 1  
    //PC6_SDA_M1               = 0,  PC6_GPIO    = 1,
    //PC7_SCL_M1               = 0,  PC7_GPIO    = 1,
    fvchip_c1_pin_set_mux(PORTC, PC6, PC6_SDA_M1); // PC6_GPIO
    fvchip_c1_pin_set_mux(PORTC, PC7, PC7_SCL_M1); // PC7_GPIO
#endif

#if 0 // test gpio
    //PC4_SDA_M2               = 0,  PC4_GPIO    = 1,
    //PC5_SCL_M2               = 0,  PC5_GPIO    = 1,
    fvchip_c1_pin_set_mux(PORTC, PC4, PC4_GPIO); // PC4_GPIO
    fvchip_c1_pin_set_mux(PORTC, PC5, PC5_GPIO); // PC5_GPIO
   
    fvchip_c1_pin_set_Dir(PORTC, PC4,GPIO_DIRECTION_OUTPUT);  // gpio output
    fvchip_c1_pin_set_Dir(PORTC, PC5,GPIO_DIRECTION_OUTPUT);  // gpio output
    while(1)
    {
        setGpio_Pin_Val(PORTC, PC4, 1);
        setGpio_Pin_Val(PORTC, PC5, 1);
        mdelay(20);
       
        setGpio_Pin_Val(PORTC, PC4, 0);
        setGpio_Pin_Val(PORTC, PC5, 0);
        mdelay(20);
    }
#endif
   
    i2c_master_init(IIC_MASTER_CH_3, 0x50);  // i2c m1
    if(IIC_CheckDevice(IIC_MASTER_CH_3, 0x50))
    {
        printf("i2c ch%d , devAddr=0x%02x no ack\r\n", IIC_MASTER_CH_3, 0x50);
        printf("stop test eeprom\r\n");
    }
    else
    {
        printf("i2c ch%d , devAddr=0x%02x has ack\r\n", IIC_MASTER_CH_3, 0x50);
       
        printf("start test eeprom\r\n");
       
        i2c_master_test_write_for_24c02(IIC_MASTER_CH_3, 0x50);  // ok
        i2c_master_test_read_for_24c02(IIC_MASTER_CH_3);  // ok
        i2c_master_test_case_write_read_100khz(IIC_MASTER_CH_3,0x50);  // ok
    }
    mdelay(100);
   
   

    while(1);

    return 0;
}

#endif

#if WORK_MODE_TEST_SPI  // spi test ok
//SCK  :  VU9P.G22   - FMC.G2  - SPI_SCK  , input
//SDI  :  VU9P.G11   - FMC.G6  - SPI_MISO , input
//SDO  :  VU9P.G21   - FMC.G3  - SPI_MOSI , output
//CSN  :  VU9P.G10   - FMC.G7  - SPI_SSN  , output
//HOLDN:  VU9P.D10   - FMC.G10 - CN15.1 (和TMS冲突)
//WPN  :  VU9P.D11   - FMC.G9  - CN15.2   , output
int main(void)
{
    //int i;
    uint32_t vecPara;
    uint32_t miePara;
   
    //打印版本
    printf("\r\n erase spi flash : \r\n");
   
    GPIOA->SWPORT_DDR |= (1<<24); //LED5
    led_onoff(PORTA, PA2, 0);
   
#if USE_DW_SPI
    spi_flash_opMode();  //test failed in vu19p
#else  // old spi
    SPI_Init();
    spi_test();
#endif  

    printf("erase spi flash done !!!\r\n");
   
    led_onoff(PORTA, PA2, 1);
   
    while(1);
   
    return 0;
}
#endif

#if WORK_MODE_TEST_WDT  // wdt test
int main(void)
{
    printf("\r\n watch-dog \r\n");
   
    watchdog_test();

    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_PWM  // PWM test OK
//pwm1:  VU9P.N17  - FMC.F16 - CN20.14  , input
//pwm2:  VU9P.C9   - FMC.C10 - LED2     , input
//pwm3:  VU9P.F11  - FMC.D8  - LED3     , output
//pwm4:  VU9P.C8   - FMC.C11 - LED4     , output
int main(void)
{
    u8 test_writeBuf[256] = {0};
    u8 test_readBuf[256]={0};
    u32 rdTemp,i;
    u32 val;
   
    printf("\r\n pwm test\r\n");
   
    pwm_test();

    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_PADMUX  // padmux test
int main(void)
{
    u8 test_writeBuf[256] = {0};
    u8 test_readBuf[256]={0};
    u32 rdTemp,i;
   
    fvchip_c1_pin_set_mux(PORTC, PC8, PC8_UART0_SOUT);
    fvchip_c1_pin_set_mux(PORTC, PC9, PC9_UART0_SIN);
    printf("\r\n pad mux test 111 \r\n");
   
    fvchip_c1_pin_set_mux(PORTC, PC8, PC8_GPIO);
    fvchip_c1_pin_set_mux(PORTC, PC9, PC9_GPIO);
    printf("\r\n pad mux test 222 \r\n");
       
    fvchip_c1_pin_set_mux(PORTC, PC8, PC8_UART0_SOUT);
    fvchip_c1_pin_set_mux(PORTC, PC9, PC9_UART0_SIN);
    printf("\r\n pad mux test 333 \r\n");
   
    GPIOA->SWPORT_DDR |= (1<<24);    // output
    GPIOA->SWPORT_DDR |= (1<<25);    // output
    GPIOA->SWPORT_DDR |= (1<<26);    // output
    GPIOA->SWPORT_DDR |= (1<<27);    // output
   
    while(1)
    {
        GPIOA->SWPORT_DR |= (1<<24);
        GPIOA->SWPORT_DR |= (1<<25);
        GPIOA->SWPORT_DR |= (1<<26);
        GPIOA->SWPORT_DR |= (1<<27);
        mdelay(200);
        GPIOA->SWPORT_DR &= ~(1<<24);
        GPIOA->SWPORT_DR &= ~(1<<25);
        GPIOA->SWPORT_DR &= ~(1<<26);
        GPIOA->SWPORT_DR &= ~(1<<27);
        mdelay(200);
    }

    return 0;
}
#endif

#if WORK_MODE_TEST_TIMER  // timer test
extern timer_handle_t timer_handle;
extern unsigned int timer0_cnt;
extern unsigned int timerX_cnt;
int main(void)
{
    u8 test_writeBuf[256] = {0};
    u8 test_readBuf[256]={0};
    u32 rdTemp,i;
    u32 val;
    dw_timer_reg_t *addr = (dw_timer_reg_t *)(CSKY_TIMER0_BASE);
   
    printf("\r\n timer test\r\n");
   
    printf("0 g_irqvector[%d]=0x%08x\r\n", TIM0_IRQn, g_irqvector[TIM0_IRQn]);

    unsigned long long systimer_start_val = my_timer_current_value();
    printf("systimer_start_val = %f\r\n",systimer_start_val);
   
    //此处打印会导致timer0过20秒才能停止
    //printf("0 addr->TxLoadCount = %d\r\n",addr->TxLoadCount);
    //printf("0 addr->TxCurrentValue = %d\r\n",addr->TxCurrentValue);
    //printf("0 addr->TxControl = %d\r\n",addr->TxControl);
    //printf("0 addr->TxIntStatus = %d\r\n",addr->TxIntStatus);
    //
    //
    //mdelay(20000);
    //
    //printf("1 addr->TxLoadCount = %d\r\n",addr->TxLoadCount);
    //printf("1 addr->TxCurrentValue = %d\r\n",addr->TxCurrentValue);
    //printf("1 addr->TxControl = %d\r\n",addr->TxControl);
    //printf("1 addr->TxIntStatus = %d\r\n",addr->TxIntStatus);
   
    unsigned long long systimer_end_val = my_timer_current_value();
    printf("systimer_end_val = %f\r\n",systimer_end_val);
   
    printf("timer0 will stop\r\n");
   
    printf("timer0_cnt=%d\r\n",timer0_cnt);
   
    clock_timer_stop();
   
    printf("CLIC->CLICCFG=0x%08x\r\n", CLIC->CLICCFG);
    printf("CLIC->CLICINFO=0x%08x\r\n", CLIC->CLICINFO);
    printf("CLIC->MINTTHRESH=0x%08x\r\n", CLIC->MINTTHRESH);
   
    for(int i=0;i<4096;i++)
    {
        if(CLIC->CLICINT[i].IE != 0)
            printf("0 CLIC->CLICINT[%d].IE=0x%08x\r\n", i, CLIC->CLICINT[i].IE);
    }
   
    printf("timer0 stop\r\n");
   
    csi_timer_uninitialize(timer_handle);
   
    printf("1 g_irqvector[%d]=0x%08x\r\n", TIM0_IRQn,g_irqvector[TIM0_IRQn]);
   
    csi_vic_disable_irq(TIM0_IRQn);
   
    for(int i=0;i<4096;i++)
    {
        if(CLIC->CLICINT[i].IE != 0)
            printf("1 CLIC->CLICINT[%d].IE=0x%08x\r\n", i, CLIC->CLICINT[i].IE);
    }
   
    printf("2 g_irqvector[%d]=0x%08x\r\n", TIM0_IRQn,g_irqvector[TIM0_IRQn]);
   
   
   
    //while(1);
   
#if 1  //// test timer1 ~timer3
    uint8_t timer_SelIdx = 1;
   
    for(timer_SelIdx=1;timer_SelIdx<5;timer_SelIdx++)
    {
        timerX_init(timer_SelIdx);
        mdelay(1);
        timerX_start(timer_SelIdx);
       
        if(timer_SelIdx==1)
            printf("g_irqvector[%d]=0x%08x\r\n", TIM1_IRQn, g_irqvector[TIM1_IRQn]);
        else if(timer_SelIdx == 2)
            printf("g_irqvector[%d]=0x%08x\r\n", TIM2_IRQn, g_irqvector[TIM2_IRQn]);
        else if(timer_SelIdx == 3)
            printf("g_irqvector[%d]=0x%08x\r\n", TIM3_IRQn, g_irqvector[TIM3_IRQn]);
        else if(timer_SelIdx == 4)
        {
            printf("not support timer int\r\n");
            break;
        }
           
        while(1)
        {
            mdelay(20);  //此处延迟必须要加才能结束
            if(timerX_cnt >= 5)
            {
                printf("timerX_cnt=%d\r\n", timerX_cnt);
                timerX_cnt = 0;
                if(timerX_stop(timer_SelIdx)==0)
                    printf("stop timer %d\r\n", timer_SelIdx);
                else
                    printf("can't stop timer %d\r\n", timer_SelIdx);
                   
                break;
            }
        }
    }
#endif

    printf("timer test done\r\n");

    while(1);
   
    return 0;
}
#endif

#if WORK_MODE_TEST_CPU_CORE  // cpu core test

int main(void)
{
    uint32_t vecPara;
    uint32_t miePara;
    uint32_t mcyclePara;
    uint32_t mVendorId;
    uint32_t mArchId;
   
    printf("\r\n cpu core test\r\n");
   
    mVendorId = __get_MVENDORID();
    printf("mVendorId is 0x%08x\r\n", mVendorId);
   
    mArchId = __get_MARCHID();
    printf("mVendorId is 0x%08x\r\n", mArchId);
   
    mcyclePara = __get_MCYCLE();
    printf("0 mcyclePara is %d\r\n", mcyclePara);
   
    mcyclePara = __get_MCYCLE();
    printf("1 mcyclePara is %d\r\n", mcyclePara);
   
    mcyclePara = __get_MCYCLE();
    printf("2 mcyclePara is %d\r\n", mcyclePara);
   
    vecPara = __get_MTVEC();
    printf("vec is 0x%08x\r\n", vecPara);
   
    miePara = __get_MIE();
    printf("mie is 0x%08x\r\n", miePara);
   
    printf("CLIC->CLICCFG=0x%08x\r\n", CLIC->CLICCFG);
    printf("CLIC->CLICINFO=0x%08x\r\n", CLIC->CLICINFO);
    printf("CLIC->MINTTHRESH=0x%08x\r\n", CLIC->MINTTHRESH);
   
   
    for(int i=0;i<4096;i++)
    {
        if(CLIC->CLICINT[i].IE != 0)
            printf("CLIC->CLICINT[%d].IE=0x%08x\r\n", i, CLIC->CLICINT[i].IE);
    }
   
    __set_MTVEC(vecPara);
   
    unsigned long long systimer_start_val = my_timer_current_value();
    mdelay(1);
    unsigned long long systimer_end_val = my_timer_current_value();
   
   
    printf("systimer_start_val = %f\r\n",systimer_start_val);
    printf("systimer_end_val = %f\r\n",systimer_end_val);

    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_INTERRUPT  // interrupt test
int main(void)
{
    printf("\r\n interrupt test\r\n");
   
    //printf("0 PORTA PA28 GPIOA->SWPORT_DR =0x%08x\r\n", GPIOA->SWPORT_DR);
    //printf("0 PORTA PA28 GPIOA->SWPORT_DDR=0x%08x\r\n", GPIOA->SWPORT_DDR);
    //printf("0 PORTA PA28 GPIOA->PORT_CTL  =0x%08x\r\n", GPIOA->PORT_CTL);
   
    //printf("0 PORTA PA28 GPIOA_CTRL->INTEN =0x%08x\r\n", GPIOA_CTRL->INTEN);
    //printf("0 PORTA PA28 GPIOA_CTRL->INTMASK=0x%08x\r\n", GPIOA_CTRL->INTMASK);
    //printf("0 PORTA PA28 GPIOA_CTRL->INTTYPE_LEVEL  =0x%08x\r\n", GPIOA_CTRL->INTTYPE_LEVEL);
    //printf("0 PORTA PA28 GPIOA_CTRL->INT_POLARITY =0x%08x\r\n", GPIOA_CTRL->INT_POLARITY);
    printf("0 PORTA PA28 GPIOA_CTRL->INTSTATUS     =0x%08x\r\n", GPIOA_CTRL->INTSTATUS);
    printf("0 PORTA PA28 GPIOA_CTRL->RAWINTSTATUS  =0x%08x\r\n", GPIOA_CTRL->RAWINTSTATUS);
    //printf("0 PORTA PA28 GPIOA_CTRL->PORTA_EOI =0x%08x\r\n", GPIOA_CTRL->PORTA_EOI);
    //printf("0 PORTA PA28 GPIOA_CTRL->EXT_PORTA=0x%08x\r\n", GPIOA_CTRL->EXT_PORTA);
    //printf("0 PORTA PA28 GPIOA_CTRL->EXT_PORTB  =0x%08x\r\n", GPIOA_CTRL->EXT_PORTB);
    //printf("0 PORTA PA28 GPIOA_CTRL->LS_SYNC  =0x%08x\r\n", GPIOA_CTRL->LS_SYNC);
   
    pad_mux_gpioA28_test();
   
    //printf("1 PORTA PA28 GPIOA->SWPORT_DR =0x%08x\r\n", GPIOA->SWPORT_DR);
    //printf("1 PORTA PA28 GPIOA->SWPORT_DDR=0x%08x\r\n", GPIOA->SWPORT_DDR);
    //printf("1 PORTA PA28 GPIOA->PORT_CTL  =0x%08x\r\n", GPIOA->PORT_CTL);
   
    //printf("1 PORTA PA28 GPIOA_CTRL->INTEN =0x%08x\r\n", GPIOA_CTRL->INTEN);
    //printf("1 PORTA PA28 GPIOA_CTRL->INTMASK=0x%08x\r\n", GPIOA_CTRL->INTMASK);
    //printf("1 PORTA PA28 GPIOA_CTRL->INTTYPE_LEVEL  =0x%08x\r\n", GPIOA_CTRL->INTTYPE_LEVEL);
    //printf("1 PORTA PA28 GPIOA_CTRL->INT_POLARITY =0x%08x\r\n", GPIOA_CTRL->INT_POLARITY);
    printf("1 PORTA PA28 GPIOA_CTRL->INTSTATUS     =0x%08x\r\n", GPIOA_CTRL->INTSTATUS);
    printf("1 PORTA PA28 GPIOA_CTRL->RAWINTSTATUS  =0x%08x\r\n", GPIOA_CTRL->RAWINTSTATUS);
    //printf("1 PORTA PA28 GPIOA_CTRL->PORTA_EOI =0x%08x\r\n", GPIOA_CTRL->PORTA_EOI);
    //printf("1 PORTA PA28 GPIOA_CTRL->EXT_PORTA=0x%08x\r\n", GPIOA_CTRL->EXT_PORTA);
    //printf("1 PORTA PA28 GPIOA_CTRL->EXT_PORTB  =0x%08x\r\n", GPIOA_CTRL->EXT_PORTB);
    //printf("1 PORTA PA28 GPIOA_CTRL->LS_SYNC  =0x%08x\r\n", GPIOA_CTRL->LS_SYNC);
   
    printf("CLIC->CLICCFG=0x%08x\r\n", CLIC->CLICCFG);
    printf("CLIC->CLICINFO=0x%08x\r\n", CLIC->CLICINFO);
    printf("CLIC->MINTTHRESH=0x%08x\r\n", CLIC->MINTTHRESH);
   
    //drv_irq_enable(GPIO0_IRQn);
   
    for(int i=0;i<4096;i++)
    {
        if(CLIC->CLICINT[i].IE != 0)
            printf("CLIC->CLICINT[%d].IE=0x%08x\r\n", i, CLIC->CLICINT[i].IE);
    }
   
    fvchip_c1_pin_set_Dir(PORTA, PA27,GPIO_DIRECTION_OUTPUT);  // gpio 27 output
    setGpio_Pin_Val(PORTA, PA27, 1);  // light on
   
    while(1)
    {
        //printf("2 PORTA PA28 GPIOA->SWPORT_DR =0x%08x\r\n", GPIOA->SWPORT_DR);
        //printf("2 PORTA PA28 GPIOA->SWPORT_DDR=0x%08x\r\n", GPIOA->SWPORT_DDR);
        //printf("2 PORTA PA28 GPIOA->PORT_CTL  =0x%08x\r\n", GPIOA->PORT_CTL);
       
        //printf("2 PORTA PA28 GPIOA_CTRL->INTEN =0x%08x\r\n", GPIOA_CTRL->INTEN);
        //printf("2 PORTA PA28 GPIOA_CTRL->INTMASK=0x%08x\r\n", GPIOA_CTRL->INTMASK);
        //printf("2 PORTA PA28 GPIOA_CTRL->INTTYPE_LEVEL  =0x%08x\r\n", GPIOA_CTRL->INTTYPE_LEVEL);
        //printf("2 PORTA PA28 GPIOA_CTRL->INT_POLARITY =0x%08x\r\n", GPIOA_CTRL->INT_POLARITY);
        //printf("2 PORTA PA28 GPIOA_CTRL->INTSTATUS     =0x%08x\r\n", GPIOA_CTRL->INTSTATUS);
        //printf("2 PORTA PA28 GPIOA_CTRL->RAWINTSTATUS  =0x%08x\r\n", GPIOA_CTRL->RAWINTSTATUS);
        //printf("2 PORTA PA28 GPIOA_CTRL->PORTA_EOI =0x%08x\r\n", GPIOA_CTRL->PORTA_EOI);
        //printf("2 PORTA PA28 GPIOA_CTRL->EXT_PORTA=0x%08x\r\n", GPIOA_CTRL->EXT_PORTA);
        //printf("2 PORTA PA28 GPIOA_CTRL->EXT_PORTB  =0x%08x\r\n", GPIOA_CTRL->EXT_PORTB);
        //printf("2 PORTA PA28 GPIOA_CTRL->LS_SYNC  =0x%08x\r\n", GPIOA_CTRL->LS_SYNC);
       
        if((GPIOA_CTRL->RAWINTSTATUS) & (1<<PA28))
        {
            //printf("find SW6 press down\r\n");
            static uint8_t ledCnt=0;
            uint32_t regVal = GPIOA_CTRL->PORTA_EOI;
           
            regVal |= (1<<PA28);
            GPIOA_CTRL->PORTA_EOI = regVal;
           
            ledCnt++;
            setGpio_Pin_Val(PORTA, PA27, (ledCnt&0x01));  // light blink
           
        }
       
        //if((GPIOA_CTRL->RAWINTSTATUS) & (1<<PA22))
        //{
        //  printf("find SW6 press down\r\n");
        //  uint32_t regVal = GPIOA_CTRL->PORTA_EOI;
        //  
        //  regVal |= (1<<PA22);
        //  
        //  
        //  GPIOA_CTRL->PORTA_EOI = regVal;
        //}
       
        //if((GPIOA_CTRL->RAWINTSTATUS) & (1<<PA23))
        //{
        //  printf("find SW6 press down\r\n");
        //  uint32_t regVal = GPIOA_CTRL->PORTA_EOI;
        //  
        //  regVal |= (1<<PA23);
        //  
        //  
        //  GPIOA_CTRL->PORTA_EOI = regVal;
        //}
       
        //mdelay(500);
    }

    return 0;
}
#endif

#if WORK_MODE_TEST_IAP  // iap test

int main(void)
{
    printf("\r\niap test interrupt\r\n");
   
    uint32_t vecPara;  
    uint32_t miePara;
    uint32_t mSp;
    uint32_t mPc;
   
    vecPara = __get_MTVEC();
    printf("x vec is 0x%08x\r\n", vecPara);
   
    mSp = __get_SP();
    printf("x sp is 0x%08x\r\n", mSp);
   
    for(int i=0;i<IMAGE_MAX_SIZE;i++)
    {
        *(uint8_t *)(IMAGE_ENTRY+i) = 0;
    }
    //
    ////读
    //for(int i=0;i<IMAGE_MAX_SIZE;i++)
    //{
    //  if(i%16 == 0)
    //  {
    //      printf("%08x: ",i);
    //  }
    //  printf("%02x ", *(uint8_t *)(IMAGE_ENTRY+i));
    //  if(i%16 == 15)
    //  {
    //      printf("\r\n");
    //  }
    //}
   
   
    //搬送程序
    readAppCodeFromSpi(IMAGE_ENTRY, IMAGE_MAX_SIZE);
    printf("readAppCodeFromSpi\r\n");
   
    //读
    for(int i=0;i<IMAGE_MAX_SIZE;i++)
    {
        if(i%16 == 0)
        {
            printf("%08x: ",i);
        }
        printf("%02x ", *(uint8_t *)(IMAGE_ENTRY+i));
        if(i%16 == 15)
        {
            printf("\r\n");
        }
       
        //if(*(uint8_t *)(IMAGE_ENTRY+i) != 0xFF)
        //{
        //  printf("%08x: %02x\r\n", i, *(uint8_t *)(IMAGE_ENTRY+i));
        //}
    }
   
    if(XMODEM_DOWNLOAD_USE_IRAM_OR_DRAM == 1)
    {
        funPtr = (void (*)(void))IMAGE_ENTRY;
    }
    else
    {
        //代码必须下载到IRAM空间才能运行    
        for(int i=0;i<IMAGE_MAX_SIZE;i++)
        {
            *(u8_t *)(APP_RUN_ADDR +i) = *(u8_t *)(IMAGE_ENTRY +i);
        }
        //memcpy((u8_t *)(APP_RUN_ADDR), (u8_t *)(IMAGE_ENTRY), IMAGE_MAX_SIZE);
           
        funPtr = (void (*)(void))APP_RUN_ADDR;
    }
   
    printf("APP_RUN_ADDR\r\n");
   
    //__set_MTVEC(vecPara);
   
    //funPtr = (void (*)(void))(APP_RUN_ADDR);
    //funPtr();
   
    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_READ_ROM  // read 32k rom
//发现BUG：读ROM再写IRAM，容易出现CPU Exception: NO.2
#define ROMCODE_ENTRY 0x00000000

int main(void)
{
    uint32_t currVecEntry, newVecEntry;
   
    printf("\r\nread rom to iram 0509\r\n");
   
    //将用于下载APP的RAM空间清0
    //memset((volatile)(uint8_t * )APP_RUN_ADDR, 0x00, IMAGE_MAX_SIZE);
    //
    //for(int i=0;i<IMAGE_MAX_SIZE;i++)
    //{
    //  if(*(u8_t *)(APP_RUN_ADDR +i) != 0x00)
    //  {
    //      printf("check iram failed! iram addr[0x%08x]=0x%x\r\n",(APP_RUN_ADDR+i),*(u8_t *)(APP_RUN_ADDR +i));
    //      return;
    //  }
    //}
    //
    //printf("check iram ok !\n\r");
    //
    ////while(1);
    //printf("read rom !\n\r");
    //for(int i=0;i<IMAGE_MAX_SIZE;i++)
    //{
    //  if(i%16 == 0)
    //  {
    //      printf("%08x: ",ROMCODE_ENTRY+i);
    //  }
    //  printf("%02x ", *(uint8_t *)(ROMCODE_ENTRY+i));
    //  if(i%16 == 15)
    //  {
    //      printf("\r\n");
    //  }
    //}
    //
    //printf("read rom ok\r\n");
    //
    printf("copy rom to iram :\n\r");
    //
    for(int i=0;i<IMAGE_MAX_SIZE;i++)
    {
        //if(i%16 == 0)
        //{
        //  printf("%08x: ",APP_RUN_ADDR+i);
        //}
       
        *(volatile u8_t *)(APP_RUN_ADDR +i) = *(volatile u8_t *)(ROMCODE_ENTRY +i);
        //*(volatile u8_t *)(APP_RUN_ADDR +i) = *(volatile u8_t *)(0x10000 +i);
        //printf("%02x ",*(volatile u8_t *)(APP_RUN_ADDR +i));
        //if(i%16 == 15)
        //{
        //  printf("\r\n");
        //}
    }
   
    //printf("copy rom to iram done\n\r");
    //printf("copy iram[0x10000] to iram[0x8000] done\n\r");
    printf("copy rom[0x0000] to iram[0x8000] done\n\r");
   
    //while(1);
   
    //for(int i=0;i<IMAGE_MAX_SIZE;i++)
    //{
    //  if(i%16 == 0)
    //  {
    //      printf("%08x: ",APP_RUN_ADDR+i);
    //  }
    //  //*(volatile u8_t *)(APP_RUN_ADDR +i) = *(volatile u8_t *)(ROMCODE_ENTRY +i);
    //  printf("%02x ", *(volatile uint8_t *)(APP_RUN_ADDR+i));
    //  if(i%16 == 15)
    //  {
    //      printf("\r\n");
    //  }
    //}
   
    printf("222\r\n");
   
    currVecEntry = __get_MTVEC();
   
   
    printf("vec base   = 0x%08x\r\n", currVecEntry&0xffff0000);
    printf("vec offset = 0x%08x\r\n", currVecEntry&0x0000ffff);
   
    newVecEntry = (currVecEntry&0x0000ffff)+APP_RUN_ADDR; // iram 0x10000
    //newVecEntry = (currVecEntry&0x0000ffff)+ROMCODE_ENTRY; // iram 0x10000
   
    //__set_MTVEC(APP_RUN_ADDR);
    __set_MTVEC(newVecEntry);
   
    funPtr = (void (*)(void))(APP_RUN_ADDR);
    //funPtr = (void (*)(void))(ROMCODE_ENTRY);
    //funPtr = (void (*)(void))(0x00010000);
   
    funPtr();
   
    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_READ_SPI_ROMCODE  //read spi rom code
int main(void)
{
    printf("\r\nread spi rom code 0509\r\n");
   
    //将用于下载APP的RAM空间清0
    memset((volatile)(uint8_t * )APP_RUN_ADDR, 0x00, IMAGE_MAX_SIZE);
   
    //SPI FLASH W25Q32初始化
#if USE_RH_SPI
    SPI_Init();
#endif

#if USE_DW_SPI
    dw_SpiFlash_Init();
#endif
   
    //搬送程序
    readAppCodeFromSpi(IMAGE_ENTRY, IMAGE_MAX_SIZE);
       
    for(int i=0;i<IMAGE_MAX_SIZE;i++)
    {
        if(i%16 == 0)
        {
            printf("%08x: ", IMAGE_ENTRY+i);
        }
        printf("%02x ", *(uint8_t *)(IMAGE_ENTRY+i));
        if(i%16 == 15)
        {
            printf("\r\n");
        }
    }
       
    //增加CHECKSUM，如CHECKSUM不对需要重新读取
    uint32_t checksum1 = calculate_crc32((uint8_t *)IMAGE_ENTRY, ARRAY_SIZE);  
    printf("checksum1=0x%08X\n", checksum1);  
       
    uint32_t checksum2 = Read_SpiFlash_FlagZone(APP_CRC_ADDR);
    printf("checksum2=0x%08X\n", checksum2);

    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_ONLY_PRINT    // print test
int main(void)
{
    printf("\r\nrom addr0 0509\r\n");
   
   
    while(1);

    return 0;
}
#endif

#if WORK_MODE_TEST_XMODEM   //xmodem test, OK

int main(void)
{
    uint32 downSize=0;
    printf("\r\nxmodem rx test\r\n");

#if 1    // with ccc xmodem ok
    while(1)
    {
        downSize = test_xmodemReceive(IMAGE_ENTRY, IMAGE_MAX_SIZE);
        //downSize = test_xmodemReceive(IMAGE_ENTRY, 21504);
        mdelay(50);
        printf("downSize=%d\r\n", downSize);
        if(downSize > 0)   // xmodem ok
        {
            //for(int i=0;i<IMAGE_MAX_SIZE;i++)
            for(int i=0;i<downSize;i++)
            {
                if(i%16 == 0)
                {
                    printf("%08x: ", IMAGE_ENTRY+i);
                }
                printf("%02x ", *(uint8_t *)(IMAGE_ENTRY+i));
                if(i%16 == 15)
                {
                    printf("\r\n");
                }
            }
        }
    }
#else     // without ccc xmodem test ok
    while(1)
    {
        if(my_XMODEM_Process() == 0)
        {
            mdelay(50);
           
            for(int i=0;i<IMAGE_MAX_SIZE;i++)
            {
                if(i%16 == 0)
                {
                    printf("%08x: ", IMAGE_ENTRY+i);
                }
                printf("%02x ", *(uint8_t *)(IMAGE_ENTRY+i));
                if(i%16 == 15)
                {
                    printf("\r\n");
                }
            }
           
            printf("my_XMODEM_Process ok, totalDownSize=%d\r\n", totalDownSize);
        }
    }
#endif
    while(1);
   
    return 0;
}
#endif

#if WORK_MODE_TEST_UART   // OK
int main(void)
{
    u32 val;
    unsigned char char8 = 'a';
   
    uart0_putch(char8);
   
    while(1)
    {
        mdelay(200);
       
        if(uart0_getch(&char8) == 0)  //正常接收1个字节
        {
            uart0_putch(char8);
           
            *(__IOM uint8_t *)(0x8000) = 0x55;
        }
    }
   
    while(1);
    return 0;
}

#endif

#if WORK_MODE_TEST_UART_PROTOCOL
int main(void)
{
    UartProto_Pin_Init();

    if (UartProto_Init(UART_PROTOCOL_USART_IDX) != 0) {
        while (1) {
            // 初始化失败，停机等待
        }
    }

    printf("BOOT: UART protocol mode started\r\n");
    printf("FW_VERSION:%d.%d.%d\r\n", FW_VERSION_MAJOR, FW_VERSION_MINOR, FW_VERSION_PATCH);

    while (1) {
        UartProto_Task();
    }
}
#endif


#if WORK_MODE_TEST_CGU   //
extern int g_system_clock;
extern void cpu_clock_switch(pll_clk_sel_t clkMode,                      // pll work freq
                             osc_pll_clk_mux_t clkMuxSel,                // mux sel
                             osc_pll_clk_div_en_t clkDivMode,            // use div or not
                             osc_pll_div_sel_t clkDivPara,               // div para
                             sys_clock_switch_t clkSwitchMode);          // switch sel
                             
static void cgu_log(uint8_t *idx)
{
    printf("%s pll cfg 0: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG0_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG0_BASE);
    //printf("%s pll cfg 1: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG1_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG1_BASE);
    //printf("%s pll cfg 2: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG2_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG2_BASE);
    //printf("%s pll cfg 3: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG3_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG3_BASE);
    //printf("%s pll cfg 4: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG4_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG4_BASE);
    //printf("%s pll cfg 5: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG5_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG5_BASE);
    //printf("%s pll cfg 6: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG6_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG6_BASE);
    //printf("%s pll cfg 7: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG7_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG7_BASE);
    //printf("%s pll cfg 8: [0x%08x]=0x%08x\r\n", idx, CLK_PLL_CORE_CFG8_BASE, *(__IOM uint32 *)CLK_PLL_CORE_CFG8_BASE);
   
    printf("%s sys cfg : [0x%08x]=0x%08x\r\n", idx, CLK_SYS_CFG_REG_BASE, *(__IOM uint32 *)CLK_SYS_CFG_REG_BASE);
    //printf("%s clk gate: [0x%08x]=0x%08x\r\n", idx, CLK_GATE_EN_REG_BASE, *(__IOM uint32 *)CLK_GATE_EN_REG_BASE);
    //printf("%s src div : [0x%08x]=0x%08x\r\n", idx, CLK_SRC_DIV_REG_BASE, *(__IOM uint32 *)CLK_SRC_DIV_REG_BASE);
}
                             
int main(void)
{
    u32 val;
    unsigned char char8 = 'a';
   
    printf("test cgu \r\n");
   
    cgu_log("cgu default");
   
    //使用外部晶振时钟
    cpu_clock_switch(PLL_80M,                      // pll work freq
                     MUX_CLK_SEL_PLL,              // mux sel
                     OSC_PLL_CLK_DIV_SET,       // use div or not
                     OSC_PLL_CLK_1DIV2,            // div para
                     USE_OSC_CLK);                 // switch sel
    cgu_log("pll80M, use osc");              
    mdelay(5000);
   
    //使用内部MUX时钟 - mux for osc
    cpu_clock_switch(PLL_48M,                      // pll work freq
                     MUX_CLK_SEL_PLL,              // mux sel
                     OSC_PLL_CLK_DIV_SET,       // use div or not
                     OSC_PLL_CLK_1DIV2,            // div para
                     USE_OSC_CLK);                 // switch sel
    cgu_log("pll48M, use osc");              
    mdelay(5000);
   
    //使用内部MUX时钟 - mux for pll, bypass
    cpu_clock_switch(PLL_20M,                      // pll work freq
                     MUX_CLK_SEL_PLL,              // mux sel
                     OSC_PLL_CLK_DIV_BYPASS,       // use div or not
                     OSC_PLL_CLK_1DIV2,            // div para
                     USE_OSC_CLK);                 // switch sel
    cgu_log("pll20M, use osc");              
    mdelay(5000);
   
    //使用内部MUX时钟 - mux for pll, 1/2 div
    printf("test mux osc clock\r\n");
    cpu_clock_switch(PLL_12M,                      // pll work freq
                     MUX_CLK_SEL_PLL,              // mux sel
                     OSC_PLL_CLK_DIV_SET,       // use div or not
                     OSC_PLL_CLK_1DIV2,            // div para
                     USE_OSC_CLK);                 // switch sel
    cgu_log("pll12M, use osc");              
    mdelay(5000);
   
    //while(1);
   
    while(1)
    {
        //使用外部晶振时钟
        printf("0 g_system_clock=%d\r\n", g_system_clock);
        mdelay(5000);
        cpu_clock_switch(PLL_48M,                      // pll work freq
                         MUX_CLK_SEL_PLL,              // mux sel
                         OSC_PLL_CLK_DIV_SET,       // use div or not
                         OSC_PLL_CLK_1DIV2,            // div para
                         USE_OSC_CLK);  //osc. failed  // switch sel
        cgu_log("pll48M, use pll, div1/2");              
       
        //使用内部复用器过来的时钟1：OSC 24M
        printf("1 g_system_clock=%d\r\n", g_system_clock);
        mdelay(5000);
        printf("\r\n 1 before cpu_clock_switch\r\n");
        cpu_clock_switch(PLL_48M,                      // pll work freq
                         MUX_CLK_SEL_PLL,              // mux sel
                         OSC_PLL_CLK_DIV_BYPASS,       // use div or not
                         OSC_PLL_CLK_1DIV4,            // div para
                         USE_MUX_CLK);  //osc. failed  // switch sel
        printf("\r\n 1 after cpu_clock_switch\r\n");
       
    }
   
    while(1);
    return 0;
}

#endif

#if WORK_MODE_TEST_IIC_FOR_GC2093_DVP
int main(void)
{  
   
    int conf_isp  = 0;
    int conf_camera = 1;
    int conf_ethphy = 0;
   
    if(conf_camera = 1){
        unsigned char i=0,j=0;
        uint8_t val1,val2;
       
        uint8_t dataChar[12]={1,2,3,4,5,6,7,8,9,10,11,12};
       
        printf("sensor gc2093 config test!\r\n");
   
    #if 0    // k410t isn't have pad mux
        //PC6_SDA_M1               = 0,  PC6_GPIO    = 1,
        //PC7_SCL_M1               = 0,  PC7_GPIO    = 1,
        fvchip_c1_pin_set_mux(PORTC, PC6, PC6_SDA_M1); // PC6_GPIO
        fvchip_c1_pin_set_mux(PORTC, PC7, PC7_SCL_M1); // PC7_GPIO
    #endif
     
    #if 0    // k410t isn't have pad mux
        //PC4_SDA_M2               = 0,  PC4_GPIO    = 1,
        //PC5_SCL_M2               = 0,  PC5_GPIO    = 1,
        fvchip_c1_pin_set_mux(PORTC, PC4, PC4_SDA_M2); // PC4_GPIO
        fvchip_c1_pin_set_mux(PORTC, PC5, PC5_SCL_M2); // PC5_GPIO
    #endif

        // gc2093
        i2c_master_init(IIC_MASTER_CH_1, GC2093_I2CADR);  // i2c m1
        i2c_master_init(IIC_MASTER_CH_2, GC2093_I2CADR);  // i2c m2
       
        if(IIC_CheckDevice(IIC_MASTER_CH_1, GC2093_I2CADR))
        {
            printf("i2c ch%d , devAddr=0x%02x no ack\r\n", IIC_MASTER_CH_1, GC2093_I2CADR);
        }
        else
        {
            printf("i2c ch%d , devAddr=0x%02x has ack\r\n", IIC_MASTER_CH_1, GC2093_I2CADR);
        }
       
        if(IIC_CheckDevice(IIC_MASTER_CH_2, GC2093_I2CADR))
        {
            printf("i2c ch%d , devAddr=0x%02x no ack\r\n", IIC_MASTER_CH_2, GC2093_I2CADR);
        }
        else
        {
            printf("i2c ch%d , devAddr=0x%02x has ack\r\n", IIC_MASTER_CH_2, GC2093_I2CADR);
        }
       
        gc2093_check_sensor_id(IIC_MASTER_CH_1);   //ok
        gc2093_check_sensor_id(IIC_MASTER_CH_2);   //ok
           
        //gc2093_set_1080p(IIC_MASTER_CH_1);
        //gc2093_set_1080p(IIC_MASTER_CH_2);
       
        //gc2093_set_1080p_hdr(IIC_MASTER_CH_1);
        //gc2093_set_1080p_hdr(IIC_MASTER_CH_2);
       
        //gc2093_init_dvp_1080p(IIC_MASTER_CH_1);
        //gc2093_init_dvp_1080p(IIC_MASTER_CH_2);
       
        gc2093_init_dvp_1080p(IIC_MASTER_CH_1);
        gc2093_init_dvp_1080p(IIC_MASTER_CH_2);
       
        //gc2093_init_dvp_640x480(IIC_MASTER_CH_1);
        //gc2093_init_dvp_640x480(IIC_MASTER_CH_2);
       
        //gc2093_start_stream(IIC_MASTER_CH_1);
        //gc2093_start_stream(IIC_MASTER_CH_2);
       
        // set frame len
        gc2093_set_frame_lenth(IIC_MASTER_CH_1, (30*1250/15));  // frame_len = 30*1250/20
        gc2093_set_frame_lenth(IIC_MASTER_CH_2, (30*1250/15));  // frame_len = 30*1250/20
       
        gc2093_fsync_master(IIC_MASTER_CH_1);
        gc2093_fsync_slave(IIC_MASTER_CH_2);
       
        gc2093_set_gain(IIC_MASTER_CH_1,64);
        gc2093_set_gain(IIC_MASTER_CH_2,64);
       
        gc2093_set_exposure(IIC_MASTER_CH_1,0x0600);
        gc2093_set_exposure(IIC_MASTER_CH_2,0x0600);
       
        //gc2093_set_gain(IIC_MASTER_CH_1,300);
        //gc2093_set_gain(IIC_MASTER_CH_2,300);
       
        //gc2093_set_exposure(IIC_MASTER_CH_1,0x0400);
        //gc2093_set_exposure(IIC_MASTER_CH_2,0x0400);
       
        printf("i2c M%d: gc2093_dvp_test \r\n", IIC_MASTER_CH_1);
        gc2093_dvp_test(IIC_MASTER_CH_1,0,2);    //normal
        //gc2093_dvp_test(IIC_MASTER_CH_1,1,2);  //test
       
        printf("i2c M%d: gc2093_dvp_test \r\n", IIC_MASTER_CH_2);
        gc2093_dvp_test(IIC_MASTER_CH_2,0,2);  //normal
        //gc2093_dvp_test(IIC_MASTER_CH_2,1,2);  //test
   
    }
   
    if(conf_ethphy = 1){
        printf("MDC & MDIO for PHY\r\n");
       
        ////phy reset
        //fvchip_c1_pin_set_mux(PORTA, PA2, PA2_GPIO);
        //fvchip_c1_pin_set_Dir(PORTA, PHY_RST,GPIO_DIRECTION_OUTPUT);  // gpio output
        ////setGpio_Pin_Val(PORTA, PHY_RST, 1);
        ////u_delay(5);
        //setGpio_Pin_Val(PORTA, PHY_RST, 0);
        ////mdelay(20);
        //u_delay(500);
        //setGpio_Pin_Val(PORTA, PHY_RST, 1);
       
        fvchip_c1_pin_set_mux(PORTA, PA0, PA0_GPIO);
        fvchip_c1_pin_set_mux(PORTA, PA1, PA1_GPIO);
        fvchip_c1_pin_set_Dir(PORTA, MDIO,GPIO_DIRECTION_OUTPUT);  // gpio output
        fvchip_c1_pin_set_Dir(PORTA, MDC,GPIO_DIRECTION_OUTPUT);  // gpio output
        uint8_t phy=1;
        rtl8211f_config(phy);
        //rtl8211f_parse_status(phy);      
    }
   

    uint32_t *c_padmux = (__IOM uint32_t *)0x4001C030UL;
    read_param(c_padmux);
    write_param(c_padmux, 0x00000000);
    read_param(c_padmux);
   
   
    if(conf_isp == 1){
       
        isp_config();
    }
   
   

    while (1)
    {    
        mdelay(200);
        // ledonoff
    }
}
#endif



#if WORK_MODE_TEST_Auto_Exposure_GC2093_DVP
int main(void)
{  
   
    int conf_isp  = 1;
    int conf_camera = 0;
    int conf_ae = 0;
   
    // Select DVP Channel
    uint32_t *c_padmux = (__IOM uint32_t *)0x4001C030UL;
    read_param(c_padmux);
    write_param(c_padmux, 0x00000000);
    read_param(c_padmux);
   
   
   
    if(conf_isp == 1){
       
        isp_config();
    }
   
    if(conf_ae == 1){
        uint32_t last_ev;
        uint32_t ev;
        uint32_t ev_temp=0x0400;
       
        int last_gain;
        int gain;
        int gain_temp=64;
//      while(1){
//          last_ev=ev_temp;
//          last_gain=gain_temp;
//          ev=ae(last_ev);
//          //gain=64;
//          if(ev >= 0x800){
//              //gain=ev*last_gain/0x800;
//              gain=80;
//              ev=0x800;
//          }else{
//              ev=ev;
//              gain=64;
//          }
//          printf("    gain:: %d\n", gain);
//          printf("    ev:: 0x%08X\n", ev);
//          
//          //config camera
//          gc2093_set_gain(IIC_MASTER_CH_1,gain);
//          gc2093_set_gain(IIC_MASTER_CH_2,gain);
//              
//          gc2093_set_exposure(IIC_MASTER_CH_1,ev);//0x0600
//          gc2093_set_exposure(IIC_MASTER_CH_2,ev
//          ev_temp = ev;
//          gain_temp=gain;
//          mdelay(20);
//      }
       
       
        while(1){
            last_ev=ev_temp;
            last_gain=gain_temp;
            ev=ae(last_ev);
            int i;
            if(i<20){
                i=i+1;
            }else{
                i=0;
            }
            if(i == 19){
                //last_ev=ev_temp;
                last_gain=gain_temp;
                ev=ae(last_ev);
                //gain=64;
                if(ev >= 0x800){
                    gain=ev*last_gain/0x800;
                    //gain=80;
                    //ev=0x800;
                }else{
                    //ev=ev;
                    gain=64;
                }
               
                //printf("    ev:: 0x%08X\n", ev);
           
                //config camera
                gc2093_set_gain(IIC_MASTER_CH_1,gain);
                gc2093_set_gain(IIC_MASTER_CH_2,gain);
               
                //gc2093_set_exposure(IIC_MASTER_CH_1,ev);//0x0600
                //gc2093_set_exposure(IIC_MASTER_CH_2,ev
                //ev_temp = ev;
                gain_temp=gain;
            }else{
                gain=gain;
            }
            printf("    gain:: %d\n", gain);
            //gain=64;
            if(ev >= 0x800){
                ev=0x800;
            }else{
                ev=ev;
            }
            //printf("    gain:: %d\n", gain);
            printf("    ev:: 0x%08X\n", ev);
           
            //config camera
//          gc2093_set_gain(IIC_MASTER_CH_1,gain);
//          gc2093_set_gain(IIC_MASTER_CH_2,gain);
               
            gc2093_set_exposure(IIC_MASTER_CH_1,ev);//0x0600
            gc2093_set_exposure(IIC_MASTER_CH_2,ev);
            ev_temp = ev;
            //gain_temp=gain;
           
           
            mdelay(20);

           
        }
//      while(1){
//          //last_ev=ev_temp;
//          last_gain=gain_temp;
//          ev=ae(last_ev);
//          //gain=64;
//          if(ev >= 0x800){
//              gain=ev*last_gain/0x800;
//              gain=80;
//              //ev=0x800;
//          }else{
//              //ev=ev;
//              gain=64;
//          }
//          printf("    gain:: %d\n", gain);
//          //printf("    ev:: 0x%08X\n", ev);
//          
//          //config camera
//          gc2093_set_gain(IIC_MASTER_CH_1,gain);
//          gc2093_set_gain(IIC_MASTER_CH_2,gain);
//              
//          //gc2093_set_exposure(IIC_MASTER_CH_1,ev);//0x0600
//          //gc2093_set_exposure(IIC_MASTER_CH_2,ev
//          //ev_temp = ev;
//          gain_temp=gain;
//          mdelay(200);
//      }
       
       
       
       
       
       
       
       
       
    }
   
   
    if(conf_camera = 1){
        unsigned char i=0,j=0;
        uint8_t val1,val2;
       
        uint8_t dataChar[12]={1,2,3,4,5,6,7,8,9,10,11,12};
       
        printf("sensor gc2093 config test!\r\n");
   
    #if 0    // k410t isn't have pad mux
        //PC6_SDA_M1               = 0,  PC6_GPIO    = 1,
        //PC7_SCL_M1               = 0,  PC7_GPIO    = 1,
        fvchip_c1_pin_set_mux(PORTC, PC6, PC6_SDA_M1); // PC6_GPIO
        fvchip_c1_pin_set_mux(PORTC, PC7, PC7_SCL_M1); // PC7_GPIO
    #endif
     
    #if 0    // k410t isn't have pad mux
        //PC4_SDA_M2               = 0,  PC4_GPIO    = 1,
        //PC5_SCL_M2               = 0,  PC5_GPIO    = 1,
        fvchip_c1_pin_set_mux(PORTC, PC4, PC4_SDA_M2); // PC4_GPIO
        fvchip_c1_pin_set_mux(PORTC, PC5, PC5_SCL_M2); // PC5_GPIO
    #endif

        // gc2093
        i2c_master_init(IIC_MASTER_CH_1, GC2093_I2CADR);  // i2c m1
        i2c_master_init(IIC_MASTER_CH_2, GC2093_I2CADR);  // i2c m2
       
        if(IIC_CheckDevice(IIC_MASTER_CH_1, GC2093_I2CADR))
        {
            printf("i2c ch%d , devAddr=0x%02x no ack\r\n", IIC_MASTER_CH_1, GC2093_I2CADR);
        }
        else
        {
            printf("i2c ch%d , devAddr=0x%02x has ack\r\n", IIC_MASTER_CH_1, GC2093_I2CADR);
        }
       
        if(IIC_CheckDevice(IIC_MASTER_CH_2, GC2093_I2CADR))
        {
            printf("i2c ch%d , devAddr=0x%02x no ack\r\n", IIC_MASTER_CH_2, GC2093_I2CADR);
        }
        else
        {
            printf("i2c ch%d , devAddr=0x%02x has ack\r\n", IIC_MASTER_CH_2, GC2093_I2CADR);
        }
       
        gc2093_check_sensor_id(IIC_MASTER_CH_1);   //ok
        gc2093_check_sensor_id(IIC_MASTER_CH_2);   //ok
           
        //gc2093_set_1080p(IIC_MASTER_CH_1);
        //gc2093_set_1080p(IIC_MASTER_CH_2);
       
        //gc2093_set_1080p_hdr(IIC_MASTER_CH_1);
        //gc2093_set_1080p_hdr(IIC_MASTER_CH_2);
       
        //gc2093_init_dvp_1080p(IIC_MASTER_CH_1);
        //gc2093_init_dvp_1080p(IIC_MASTER_CH_2);
       
        gc2093_init_dvp_1080p(IIC_MASTER_CH_1);
        gc2093_init_dvp_1080p(IIC_MASTER_CH_2);
       
        //gc2093_init_dvp_640x480(IIC_MASTER_CH_1);
        //gc2093_init_dvp_640x480(IIC_MASTER_CH_2);
       
        //gc2093_start_stream(IIC_MASTER_CH_1);
        //gc2093_start_stream(IIC_MASTER_CH_2);
       
        // set frame len
        gc2093_set_frame_lenth(IIC_MASTER_CH_1, (30*1250/15));  // frame_len = 30*1250/20
        gc2093_set_frame_lenth(IIC_MASTER_CH_2, (30*1250/15));  // frame_len = 30*1250/20
       
        gc2093_fsync_master(IIC_MASTER_CH_1);
        gc2093_fsync_slave(IIC_MASTER_CH_2);
       
        gc2093_set_gain(IIC_MASTER_CH_1,64);
        gc2093_set_gain(IIC_MASTER_CH_2,64);
       
        gc2093_set_exposure(IIC_MASTER_CH_1,0x0400);//0x0600
        gc2093_set_exposure(IIC_MASTER_CH_2,0x0400);
       
        //gc2093_set_gain(IIC_MASTER_CH_1,300);
        //gc2093_set_gain(IIC_MASTER_CH_2,300);
       
        //gc2093_set_exposure(IIC_MASTER_CH_1,0x0400);
        //gc2093_set_exposure(IIC_MASTER_CH_2,0x0400);
       
        printf("i2c M%d: gc2093_dvp_test \r\n", IIC_MASTER_CH_1);
        gc2093_dvp_test(IIC_MASTER_CH_1,0,2);    //normal
        //gc2093_dvp_test(IIC_MASTER_CH_1,1,2);  //test
       
        printf("i2c M%d: gc2093_dvp_test \r\n", IIC_MASTER_CH_2);
        gc2093_dvp_test(IIC_MASTER_CH_2,0,2);  //normal
        //gc2093_dvp_test(IIC_MASTER_CH_2,1,2);  //test
   
    }


   
   

    while (1)
    {    
        mdelay(200);
        // ledonoff
    }
}
#endif
