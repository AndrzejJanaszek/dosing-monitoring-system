from dms.config.models import InputConfig, TankConfig


def tank_config(
    tank_id: int, dispense_pin: int, refill_pin: int, active_level: int = 0
) -> TankConfig:
    return TankConfig(
        id=tank_id,
        name=f"Tank {tank_id}",
        silo_id=1,
        dispense=InputConfig(pin=dispense_pin, active_level=active_level),
        refill=InputConfig(pin=refill_pin, active_level=active_level),
    )
