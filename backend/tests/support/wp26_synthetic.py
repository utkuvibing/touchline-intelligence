"""Label-balanced fixed-16-column synthetic rows for WP2.6 tests."""

from touchline.modeling.preprocessing import ShotRow


def wp26_rows() -> list[ShotRow]:
    patterns = [
        "From Corner",
        "From Counter",
        "From Free Kick",
        "From Goal Kick",
        "From Keeper",
        "From Kick Off",
        "From Throw In",
        "Regular Play",
    ]
    rows: list[ShotRow] = []
    for index in range(400):
        body = ("Head", "Left Foot", "Right Foot")[index % 3]
        technique = ("Half Volley", "Volley", "Normal")[index % 3]
        pattern = patterns[index % len(patterns)]
        if index < 10:
            body, technique, pattern = "Other", "Backheel", "Other"
        rows.append(
            ShotRow(
                shot_id=f"mlp-{index:04d}",
                match_id=index // 4,
                fold=index % 5,
                competition_id=43,
                season_id=3,
                y=1 if index % 11 == 0 else 0,
                distance_to_goal=8.0 + float(index % 35),
                visible_goal_angle=0.05 + float(index % 20) / 40.0,
                body_part_name=body,
                technique_name=technique,
                play_pattern_name=pattern,
                first_time=True if index % 13 == 0 else None,
                under_pressure=True if index % 7 == 0 else None,
            )
        )
    return rows
