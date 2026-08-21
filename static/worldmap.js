/**
 * NodePool 世界地图模块
 * 使用 ECharts 绘制世界地图 + 节点散点分布
 */

// 备用国家坐标（当 ECharts 地图数据未加载时使用 SVG 散点）
const COUNTRY_COORDS = {
    'US': [ -95.7129, 37.0902 ], 'CN': [ 104.1954, 35.8617 ],
    'JP': [ 138.2529, 36.2048 ], 'KR': [ 127.7669, 35.9078 ],
    'SG': [ 103.8198, 1.3521 ], 'HK': [ 114.1694, 22.3193 ],
    'TW': [ 120.9605, 23.6978 ], 'DE': [ 10.4515, 51.1657 ],
    'FR': [ 1.8883, 46.6034 ], 'GB': [ -3.4360, 55.3781 ],
    'NL': [ 5.2913, 52.1326 ], 'CA': [ -106.3468, 56.1304 ],
    'AU': [ 133.7751, -25.2744 ], 'RU': [ 105.3188, 61.5240 ],
    'BR': [ -51.9253, -14.2350 ], 'IN': [ 78.9629, 20.5937 ],
    'ID': [ 113.9213, -0.7893 ], 'MY': [ 101.9758, 4.2105 ],
    'PH': [ 121.7740, 12.8797 ], 'TH': [ 100.9925, 15.8700 ],
    'VN': [ 108.2772, 14.0583 ], 'ZA': [ 22.9375, -30.5595 ],
    'AE': [ 53.8478, 23.4241 ], 'IL': [ 34.8516, 31.0461 ],
    'TR': [ 35.2433, 38.9637 ], 'SE': [ 18.6435, 60.1282 ],
    'NO': [ 8.4689, 60.4720 ], 'FI': [ 25.7482, 61.9241 ],
    'DK': [ 9.5018, 56.2639 ], 'PL': [ 19.1451, 51.9194 ],
    'CZ': [ 15.4730, 49.8175 ], 'AT': [ 14.5501, 47.5162 ],
    'CH': [ 8.2275, 46.8182 ], 'ES': [ -3.7492, 40.4637 ],
    'PT': [ -8.2245, 39.3999 ], 'IT': [ 12.5674, 41.8719 ],
    'BE': [ 4.3517, 50.8503 ], 'IE': [ -8.2439, 53.4129 ],
    'EE': [ 25.0136, 58.5953 ], 'LV': [ 24.6032, 56.8796 ],
    'LT': [ 23.8813, 55.1694 ], 'UA': [ 31.1656, 48.3794 ],
    'RO': [ 24.9668, 45.9432 ], 'BG': [ 42.7339, 25.4858 ],
    'GR': [ 21.8243, 39.0742 ], 'AR': [ -63.6167, -38.4161 ],
    'MX': [ -102.5528, 23.6345 ], 'CL': [ -71.5430, -35.6751 ],
    'PE': [ -75.0152, -9.1900 ], 'KZ': [ 66.9237, 48.0196 ],
    'IR': [ 53.6880, 32.4279 ], 'PK': [ 69.3451, 30.3753 ],
    'BD': [ 90.3563, 23.6850 ], 'MM': [ 95.9560, 21.9162 ],
    'KH': [ 104.9910, 12.5657 ], 'LA': [ 19.8563, 102.4955 ],
    'MO': [ 113.5439, 22.1987 ], 'NZ': [ 174.8860, -40.9006 ],
    'MV': [ 73.2207, 3.2028 ], 'LK': [ 80.7718, 7.8731 ],
    'SA': [ 45.0792, 23.8859 ], 'QA': [ 51.1839, 25.3548 ],
    'OM': [ 55.9754, 21.4735 ], 'KW': [ 29.3117, 47.4818 ],
    'MA': [ -7.0926, 31.7917 ], 'DZ': [ 1.6596, 28.0339 ],
    'TN': [ 9.5375, 33.8869 ], 'KE': [ 37.9062, -0.0236 ],
    'ET': [ 40.4897, 9.1450 ], 'MG': [ 46.8691, -18.7669 ],
    'AO': [ 17.8739, -11.2027 ], 'MZ': [ 35.5296, -18.6657 ],
    'NG': [ 8.6753, 9.0820 ], 'EG': [ 30.8025, 26.8206 ],
};

// Emoji 国旗 → 国家代码映射
const EMOJI_TO_CODE = {
    '🇺🇸': 'US', '🇨🇳': 'CN', '🇯🇵': 'JP', '🇰🇷': 'KR',
    '🇸🇬': 'SG', '🇭🇰': 'HK', '🇹🇼': 'TW', '🇩🇪': 'DE',
    '🇫🇷': 'FR', '🇬🇧': 'GB', '🇳🇱': 'NL', '🇨🇦': 'CA',
    '🇦🇺': 'AU', '🇷🇺': 'RU', '🇧🇷': 'BR', '🇮🇳': 'IN',
    '🇮🇩': 'ID', '🇲🇾': 'MY', '🇵🇭': 'PH', '🇹🇭': 'TH',
    '🇻🇳': 'VN', '🇿🇦': 'ZA', '🇦🇪': 'AE', '🇮🇱': 'IL',
    '🇹🇷': 'TR', '🇸🇪': 'SE', '🇳🇴': 'NO', '🇫🇮': 'FI',
    '🇩🇰': 'DK', '🇵🇱': 'PL', '🇨🇿': 'CZ', '🇦🇹': 'AT',
    '🇨🇭': 'CH', '🇪🇸': 'ES', '🇵🇹': 'PT', '🇮🇹': 'IT',
    '🇧🇪': 'BE', '🇮🇪': 'IE', '🇪🇪': 'EE', '🇱🇻': 'LV',
    '🇱🇹': 'LT', '🇺🇦': 'UA', '🇷🇴': 'RO', '🇧🇬': 'BG',
    '🇬🇷': 'GR', '🇦🇷': 'AR', '🇲🇽': 'MX', '🇨🇱': 'CL',
    '🇵🇪': 'PE', '🇰🇿': 'KZ', '🇮🇷': 'IR', '🇵🇰': 'PK',
    '🇧🇩': 'BD', '🇲🇲': 'MM', '🇰🇭': 'KH', '🇱🇦': 'LA',
    '🇲🇴': 'MO', '🇳🇿': 'NZ', '🇱🇰': 'LK', '🇸🇦': 'SA',
    '🇶🇦': 'QA', '🇴🇲': 'OM', '🇰🇼': 'KW', '🇲🇦': 'MA',
    '🇩🇿': 'DZ', '🇹🇳': 'TN', '🇰🇪': 'KE', '🇪🇹': 'ET',
    '🇲🇬': 'MG', '🇦🇴': 'AO', '🇲🇿': 'MZ', '🇳🇬': 'NG',
    '🇪🇬': 'EG',
};

function emojiToCode(emoji) {
    return EMOJI_TO_CODE[emoji] || emoji;
}

class WorldMap {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.mapData = null;
    }

    async init() {
        if (!this.container) return;
        this.chart = echarts.init(this.container, 'dark');
        await this.loadData();
        window.addEventListener('resize', () => this.chart && this.chart.resize());
    }

    async loadData() {
        try {
            const res = await fetch('/api/map');
            this.mapData = await res.json();
            this.render();
        } catch (e) {
            console.error('Failed to load map data:', e);
            this.container.innerHTML = '<div class="empty">加载地图数据失败</div>';
        }
    }

    render() {
        if (!this.chart || !this.mapData) return;

        const { countries, scatter } = this.mapData;

        // 转换为散点数据
        const scatterData = countries.map(c => ({
            name: c.name,
            value: [c.lng, c.lat, c.count],
            count: c.count,
            avgScore: c.avg_score
        }));

        // 使用 GeoJSON 世界地图
        const option = {
            tooltip: {
                trigger: 'item',
                formatter: (params) => {
                    if (params.seriesType === 'scatter') {
                        return `<strong>${params.data.name}</strong><br/>
                            🖥 节点数: ${params.data.count}<br/>
                            ⭐ 平均评分: ${params.data.avgScore || '--'}`;
                    }
                    return params.name;
                }
            },
            visualMap: {
                min: 0,
                max: Math.max(...countries.map(c => c.count), 50),
                text: ['多', '少'],
                inRange: {
                    color: ['#1a1a2e', '#16213e', '#0f3460', '#e94560']
                },
                calculable: true,
                left: 'left',
                bottom: 20
            },
            geo: {
                map: 'world',
                roam: true,
                zoom: 1.2,
                center: [15, 20],
                label: {
                    show: false
                },
                itemStyle: {
                    areaColor: '#1e293b',
                    borderColor: '#334155',
                    borderWidth: 1
                },
                emphasis: {
                    itemStyle: {
                        areaColor: '#0ea5e9'
                    },
                    label: {
                        show: true,
                        color: '#fff'
                    }
                }
            },
            series: [{
                name: '节点分布',
                type: 'scatter',
                coordinateSystem: 'geo',
                data: scatterData,
                symbolSize: (val) => Math.max(8, Math.min(40, val[2] * 2)),
                encode: {
                    value: 2
                },
                label: {
                    formatter: '{b}',
                    position: 'right',
                    show: false
                },
                emphasis: {
                    label: {
                        show: true
                    }
                },
                itemStyle: {
                    color: '#38bdf8',
                    shadowBlur: 10,
                    shadowColor: '#38bdf880'
                }
            }, {
                name: '热门地区',
                type: 'effectScatter',
                coordinateSystem: 'geo',
                data: scatterData.filter(d => d.count >= 5),
                symbolSize: (val) => Math.max(12, Math.min(50, val[2] * 2.5)),
                rippleEffect: {
                    brushType: 'stroke',
                    scale: 4
                },
                label: {
                    formatter: '{b}',
                    position: 'right',
                    show: true,
                    color: '#e2e8f0',
                    fontSize: 11
                },
                itemStyle: {
                    color: '#e94560',
                    shadowBlur: 20,
                    shadowColor: '#e9456080'
                }
            }]
        };

        this.chart.setOption(option);
    }

    refresh() {
        this.loadData();
    }
}

// 导出
window.WorldMap = WorldMap;