"""Shared synthetic development cohort for the WP2.4 integration tests.

A 10-match synthetic population (two development matches per fold, matched 1:1 across goals and
saves so every validation fold contains both classes) plus calibration/holdout matches that must
never reach the loader. Imported by the dry-run CLI test and the cross-process artifact test so
the two exercise the identical population.
"""

from __future__ import annotations

import psycopg

from touchline.ingest.migrate import apply_migrations


def build_assignments() -> str:
    lines = ["match_id,competition_id,season_id,match_date,split,fold"]
    for i in range(10):
        if i < 5:
            line = f"{200 + i},43,3,2018-06-{14 + i:02d},development,{i % 5}"
        else:
            line = f"{200 + i},55,43,2020-06-{11 + i - 5:02d},development,{i % 5}"
        lines.append(line)
    return "\n".join(lines) + "\n"


SYN_ASSIGNMENTS = build_assignments()
EXPECTED_SHOTS = 20
EXPECTED_MATCHES = 10
EXPECTED_FOLDS = {0: 4, 1: 4, 2: 4, 3: 4, 4: 4}


def seed_cohort(conn: psycopg.Connection) -> None:
    """Migrate and seed the isolated schema with the synthetic four-scope population.

    Matches 200..204 are WC 2018, 205..209 are Euro 2020 (all development). Matches 230
    (calibration) and 240 (holdout) exist in the database but are absent from ``SYN_ASSIGNMENTS``,
    proving the loader never touches them.
    """
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions VALUES "
            "(43, 'World Cup', 'International'), (55, 'European Championship', 'International')"
        )
        cur.execute(
            "INSERT INTO seasons VALUES (3, '2018'), (43, '2020'), (106, '2022'), (282, '2024')"
        )
        cur.execute(
            "INSERT INTO competition_seasons VALUES (43, 3), (55, 43), (43, 106), (55, 282)"
        )
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute("INSERT INTO players VALUES (10, 'Shooter')")

        for i in range(10):
            match_id = 200 + i
            comp, season, date = (
                (43, 3, f"2018-06-{14 + i:02d}") if i < 5 else (55, 43, f"2020-06-{11 + i - 5:02d}")
            )
            cur.execute(
                "INSERT INTO matches (match_id, competition_id, season_id, match_date, "
                "home_team_id, away_team_id, home_score, away_score) "
                "VALUES (%s, %s, %s, %s::date, 1, 2, 0, 0)",
                (match_id, comp, season, date),
            )
            cur.execute(
                "INSERT INTO match_teams VALUES (%s, 1, 'home'), (%s, 2, 'away')",
                (match_id, match_id),
            )

        for match_id, comp, season, date in (
            (230, 43, 106, "2022-11-20"),
            (240, 55, 282, "2024-06-14"),
        ):
            cur.execute(
                "INSERT INTO matches (match_id, competition_id, season_id, match_date, "
                "home_team_id, away_team_id, home_score, away_score) "
                "VALUES (%s, %s, %s, %s::date, 1, 2, 0, 0)",
                (match_id, comp, season, date),
            )
            cur.execute(
                "INSERT INTO match_teams VALUES (%s, 1, 'home'), (%s, 2, 'away')",
                (match_id, match_id),
            )

        for i in range(10):
            match_id = 200 + i
            for shot_index, goal in ((0, True), (1, False)):
                number = 2 * i + shot_index + 1
                location_x = 88.0 + (number % 13)
                location_y = 30.0 + (number % 9)
                cur.execute(
                    """
                    INSERT INTO events (
                        event_id, match_id, event_index, period, team_id, player_id,
                        event_type_name, location_x, location_y, play_pattern_id,
                        play_pattern_name, under_pressure
                    ) VALUES (%s::uuid, %s, %s, 1, 1, 10, 'Shot', %s, %s, 1, 'Regular Play', %s)
                    """,
                    (
                        f"00000000-0000-0000-0000-{number:012d}",
                        match_id,
                        shot_index + 1,
                        location_x,
                        location_y,
                        True if i == 0 else None,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO shots (
                        event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                        technique_id, technique_name, shot_type_id, shot_type_name, first_time
                    ) VALUES (%s::uuid, %s, %s, 40, 'Right Foot', 93, 'Normal', 87, 'Open Play', %s)
                    """,
                    (
                        f"00000000-0000-0000-0000-{number:012d}",
                        97 if goal else 96,
                        "Goal" if goal else "Saved",
                        True if i in (1, 2) and not shot_index else None,
                    ),
                )

        # Calibration and holdout shots exist in the database but are not in the assignment CSV.
        for number, match_id, goal in ((81, 230, False), (82, 240, True)):
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, team_id, player_id,
                    event_type_name, location_x, location_y, play_pattern_id, play_pattern_name
                ) VALUES (%s::uuid, %s, 1, 1, 1, 10, 'Shot', %s, %s, 1, 'Regular Play')
                """,
                (f"00000000-0000-0000-0000-{number:012d}", match_id, 100.0, 40.0),
            )
            cur.execute(
                """
                INSERT INTO shots (
                    event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                    technique_id, technique_name, shot_type_id, shot_type_name
                ) VALUES (%s::uuid, %s, %s, 40, 'Right Foot', 93, 'Normal', 87, 'Open Play')
                """,
                (
                    f"00000000-0000-0000-0000-{number:012d}",
                    97 if goal else 96,
                    "Goal" if goal else "Saved",
                ),
            )
    conn.commit()
