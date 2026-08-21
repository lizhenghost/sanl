"""
世界地图坐标数据
国家/地区代码 → 经纬度坐标
用于 ECharts 世界地图可视化
"""
import json


# 国家代码 → 经纬度 (从 ip-api 和 MaxMind 聚合)
COUNTRY_COORDS = {
    "🇺🇸": {"lat": 37.0902, "lng": -95.7129, "name": "美国"},
    "🇨🇳": {"lat": 35.8617, "lng": 104.1954, "name": "中国"},
    "🇯🇵": {"lat": 36.2048, "lng": 138.2529, "name": "日本"},
    "🇰🇷": {"lat": 35.9078, "lng": 127.7669, "name": "韩国"},
    "🇸🇬": {"lat": 1.3521, "lng": 103.8198, "name": "新加坡"},
    "🇭🇰": {"lat": 22.3193, "lng": 114.1694, "name": "香港"},
    "🇹🇼": {"lat": 23.6978, "lng": 120.9605, "name": "台湾"},
    "🇩🇪": {"lat": 51.1657, "lng": 10.4515, "name": "德国"},
    "🇫🇷": {"lat": 46.6034, "lng": 1.8883, "name": "法国"},
    "🇬🇧": {"lat": 55.3781, "lng": -3.4360, "name": "英国"},
    "🇳🇱": {"lat": 52.1326, "lng": 5.2913, "name": "荷兰"},
    "🇨🇦": {"lat": 56.1304, "lng": -106.3468, "name": "加拿大"},
    "🇦🇺": {"lat": -25.2744, "lng": 133.7751, "name": "澳大利亚"},
    "🇷🇺": {"lat": 61.5240, "lng": 105.3188, "name": "俄罗斯"},
    "🇧🇷": {"lat": -14.2350, "lng": -51.9253, "name": "巴西"},
    "🇮🇳": {"lat": 20.5937, "lng": 78.9629, "name": "印度"},
    "🇮🇩": {"lat": -0.7893, "lng": 113.9213, "name": "印尼"},
    "🇲🇾": {"lat": 4.2105, "lng": 101.9758, "name": "马来西亚"},
    "🇵🇭": {"lat": 12.8797, "lng": 121.7740, "name": "菲律宾"},
    "🇹🇭": {"lat": 15.8700, "lng": 100.9925, "name": "泰国"},
    "🇻🇳": {"lat": 14.0583, "lng": 108.2772, "name": "越南"},
    "🇿🇦": {"lat": -30.5595, "lng": 22.9375, "name": "南非"},
    "🇳🇬": {"lat": 9.0820, "lng": 8.6753, "name": "尼日利亚"},
    "🇪🇬": {"lat": 26.8206, "lng": 30.8025, "name": "埃及"},
    "🇦🇪": {"lat": 23.4241, "lng": 53.8478, "name": "阿联酋"},
    "🇮🇱": {"lat": 31.0461, "lng": 34.8516, "name": "以色列"},
    "🇹🇷": {"lat": 38.9637, "lng": 35.2433, "name": "土耳其"},
    "🇸🇪": {"lat": 60.1282, "lng": 18.6435, "name": "瑞典"},
    "🇳🇴": {"lat": 60.4720, "lng": 8.4689, "name": "挪威"},
    "🇫🇮": {"lat": 61.9241, "lng": 25.7482, "name": "芬兰"},
    "🇩🇰": {"lat": 56.2639, "lng": 9.5018, "name": "丹麦"},
    "🇵🇱": {"lat": 51.9194, "lng": 19.1451, "name": "波兰"},
    "🇨🇿": {"lat": 49.8175, "lng": 15.4730, "name": "捷克"},
    "🇦🇹": {"lat": 47.5162, "lng": 14.5501, "name": "奥地利"},
    "🇨🇭": {"lat": 46.8182, "lng": 8.2275, "name": "瑞士"},
    "🇪🇸": {"lat": 40.4637, "lng": -3.7492, "name": "西班牙"},
    "🇵🇹": {"lat": 39.3999, "lng": -8.2245, "name": "葡萄牙"},
    "🇮🇹": {"lat": 41.8719, "lng": 12.5674, "name": "意大利"},
    "🇧🇪": {"lat": 50.8503, "lng": 4.3517, "name": "比利时"},
    "🇮🇪": {"lat": 53.4129, "lng": -8.2439, "name": "爱尔兰"},
    "🇪🇪": {"lat": 58.5953, "lng": 25.0136, "name": "爱沙尼亚"},
    "🇱🇻": {"lat": 56.8796, "lng": 24.6032, "name": "拉脱维亚"},
    "🇱🇹": {"lat": 55.1694, "lng": 23.8813, "name": "立陶宛"},
    "🇺🇦": {"lat": 48.3794, "lng": 31.1656, "name": "乌克兰"},
    "🇷🇴": {"lat": 45.9432, "lng": 24.9668, "name": "罗马尼亚"},
    "🇧🇬": {"lat": 42.7339, "lng": 25.4858, "name": "保加利亚"},
    "🇬🇷": {"lat": 39.0742, "lng": 21.8243, "name": "希腊"},
    "🇦🇷": {"lat": -38.4161, "lng": -63.6167, "name": "阿根廷"},
    "🇲🇽": {"lat": 23.6345, "lng": -102.5528, "name": "墨西哥"},
    "🇨🇱": {"lat": -35.6751, "lng": -71.5430, "name": "智利"},
    "🇵🇪": {"lat": -9.1900, "lng": -75.0152, "name": "秘鲁"},
    "🇰🇿": {"lat": 48.0196, "lng": 66.9237, "name": "哈萨克斯坦"},
    "🇮🇷": {"lat": 32.4279, "lng": 53.6880, "name": "伊朗"},
    "🇵🇰": {"lat": 30.3753, "lng": 69.3451, "name": "巴基斯坦"},
    "🇧🇩": {"lat": 23.6850, "lng": 90.3563, "name": "孟加拉国"},
    "🇲🇲": {"lat": 21.9162, "lng": 95.9560, "name": "缅甸"},
    "🇰🇭": {"lat": 12.5657, "lng": 104.9910, "name": "柬埔寨"},
    "🇱🇦": {"lat": 19.8563, "lng": 102.4955, "name": "老挝"},
    "🇲🇴": {"lat": 22.1987, "lng": 113.5439, "name": "澳门"},
    "🇳🇿": {"lat": -40.9006, "lng": 174.8860, "name": "新西兰"},
    "🇲🇻": {"lat": 3.2028, "lng": 73.2207, "name": "马尔代夫"},
    "🇱🇰": {"lat": 7.8731, "lng": 80.7718, "name": "斯里兰卡"},
    "🇸🇦": {"lat": 23.8859, "lng": 45.0792, "name": "沙特阿拉伯"},
    "🇶🇦": {"lat": 25.3548, "lng": 51.1839, "name": "卡塔尔"},
    "🇴🇲": {"lat": 21.4735, "lng": 55.9754, "name": "阿曼"},
    "🇰🇼": {"lat": 29.3117, "lng": 47.4818, "name": "科威特"},
    "🇲🇦": {"lat": 31.7917, "lng": -7.0926, "name": "摩洛哥"},
    "🇩🇿": {"lat": 28.0339, "lng": 1.6596, "name": "阿尔及利亚"},
    "🇹🇳": {"lat": 33.8869, "lng": 9.5375, "name": "突尼斯"},
    "🇰🇪": {"lat": -0.0236, "lng": 37.9062, "name": "肯尼亚"},
    "🇪🇹": {"lat": 9.1450, "lng": 40.4897, "name": "埃塞俄比亚"},
    "🇲🇬": {"lat": -18.7669, "lng": 46.8691, "name": "马达加斯加"},
    "🇦🇴": {"lat": -11.2027, "lng": 17.8739, "name": "安哥拉"},
    "🇲🇿": {"lat": -18.6657, "lng": 35.5296, "name": "莫桑比克"},
    "🇨🇩": {"lat": -4.0383, "lng": 21.7587, "name": "刚果民主共和国"},
    "🇨🇮": {"lat": 7.5399, "lng": -5.5471, "name": "科特迪瓦"},
    "🇬🇭": {"lat": 7.9465, "lng": -1.0232, "name": "加纳"},
}


def get_country_coords(country_code: str) -> dict:
    """获取国家坐标"""
    return COUNTRY_COORDS.get(country_code, {"lat": 0, "lng": 0, "name": country_code})


def get_map_data(nodes_data: list) -> dict:
    """
    从节点列表生成地图数据
    返回格式: {countries: [{name, code, count, lat, lng, avg_score}], scatter: [{name, value, lat, lng}]}
    """
    from collections import defaultdict

    country_groups = defaultdict(list)
    for node in nodes_data:
        country = node.get("country") or "unknown"
        country_groups[country].append(node)

    countries = []
    scatter = []
    for code, nodes_in_country in country_groups.items():
        coord = get_country_coords(code)
        if coord["lat"] == 0 and coord["lng"] == 0:
            continue
        avg_score = sum(n.get("score") or 0 for n in nodes_in_country) / len(nodes_in_country)
        countries.append({
            "code": code,
            "name": coord["name"],
            "count": len(nodes_in_country),
            "lat": coord["lat"],
            "lng": coord["lng"],
            "avg_score": round(avg_score, 1)
        })
        # 每个节点作为散点
        for node in nodes_in_country[:50]:  # 最多 50 个散点
            scatter.append({
                "name": node.get("node_name") or "",
                "value": [coord["lng"] + (hash(node.get("id", "")) % 100) / 1000 - 0.05,
                          coord["lat"] + (hash(node.get("node_name", "")) % 100) / 1000 - 0.05,
                          node.get("score") or 0],
                "speed": node.get("download_speed") or 0
            })

    return {
        "countries": sorted(countries, key=lambda x: x["count"], reverse=True),
        "scatter": scatter
    }