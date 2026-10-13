"""Single source of truth: PDU addresses, engineering units and IEC IOAs."""
SIGNALS = [
    ('power_kw', 'Aktif güç', 'kW'),
    ('daily_kwh', 'Günlük üretim', 'kWh'),
    ('total_kwh', 'Toplam üretim', 'kWh'),
    ('reactive_kvar', 'Reaktif güç', 'kvar'),
    ('apparent_kva', 'Görünür güç', 'kVA'),
    ('power_factor', 'Güç faktörü', ''),
    ('v_l1n', 'L1-N gerilim', 'V'),
    ('v_l2n', 'L2-N gerilim', 'V'),
    ('v_l3n', 'L3-N gerilim', 'V'),
    ('i_l1', 'L1 akım', 'A'),
    ('i_l2', 'L2 akım', 'A'),
    ('i_l3', 'L3 akım', 'A'),
    ('frequency', 'Frekans', 'Hz'),
    ('dc_voltage', 'DC gerilim', 'V'),
    ('dc_current', 'DC akım', 'A'),
    ('dc_power_kw', 'DC güç', 'kW'),
    ('temperature', 'İç sıcaklık', '°C'),
    ('efficiency', 'Dönüşüm verimi', '%'),
    ('status', 'SunSpec çalışma durumu (St)', ''),
    ('alarm_code', 'SunSpec Evt1 — alt 16 bit', ''),
    ('irradiance', 'Panel düzlemi ışınımı', 'W/m²'),
    ('rated_kw', 'Nominal güç', 'kW'),
    ('v_l1l2', 'L1-L2 gerilim', 'V'),
    ('v_l2l3', 'L2-L3 gerilim', 'V'),
    ('v_l3l1', 'L3-L1 gerilim', 'V'),
    ('evt1_hi', 'SunSpec Evt1 — üst 16 bit', ''),
    ('evt2_lo', 'SunSpec Evt2 — alt 16 bit (ayrılmış)', ''),
    ('evt2_hi', 'SunSpec Evt2 — üst 16 bit (ayrılmış)', ''),
]
# Analyzer has no DC bus / conversion efficiency / inverter heatsink temperature.
ANALYZER_KEYS = {k for k, _, _ in SIGNALS} - {'dc_voltage','dc_current','dc_power_kw','temperature','efficiency','irradiance'}

def mappings():
    for unit in range(1, 12):
        for index, (key, label, engineering_unit) in enumerate(SIGNALS):
            if unit == 11 and key not in ANALYZER_KEYS:
                continue
            yield dict(unit_id=unit, device=('Analizör' if unit == 11 else f'İnvertör {unit:02}'),
                       key=key, label=label, unit=engineering_unit, pdu_address=index*2,
                       register_reference=40001+index*2, register_count=2,
                       data_type='FLOAT32', byte_order='ABCD', function_code=3,
                       common_address=1, ioa=unit*1000+index+1, iec_type='M_ME_NC_1', type_id=13, scale=1)
