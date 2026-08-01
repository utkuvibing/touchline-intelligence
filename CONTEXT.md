# Touchline Intelligence domain language

Touchline turns a pinned football event-data source into traceable research entities. These terms
distinguish source membership, participation evidence, events, and model-facing shot facts without
claiming more than the recorded data supports.

## Language

**Competition-season**:
A specific edition of a competition, identified by the source competition and season identifiers
together.
_Avoid_: Competition, when the season is also part of the identity

**Match**:
One scheduled game within a competition-season, between one home team and one away team.
_Avoid_: Fixture, game

**Team**:
A source-identified football team encountered in the selected matches.
_Avoid_: Club, because the current cohort contains national teams

**Player**:
A source-identified football player. Names, nicknames, and countries are source labels that can
vary between match-scoped records and are not the player's identity.
_Avoid_: Appearance, lineup member

**Lineup membership**:
A source record placing a player in one team's match lineup, whether or not a position interval or
event proves that the player appeared.
_Avoid_: Appearance, minutes played

**Position interval**:
A source-recorded position assignment with match-clock boundaries and reasons. It is preserved as
recorded and is not assumed to form a clean chronology.
_Avoid_: Player minutes

**Possession**:
A source-numbered sequence within one match, attributed by the source to one of the match teams.
_Avoid_: Attack, because possession boundaries are provider-defined

**Event**:
One source-recorded match action with a stable identifier and source order, including event types
that have no player or pitch location.
_Avoid_: Action, row

**Event relation**:
A directed source reference from one event to another event in the same match; it is not assumed to
be reciprocal.
_Avoid_: Undirected link

**Shot**:
A typed detail record for an Event whose source event type is Shot, whether or not optional
attribution or location was recorded.
_Avoid_: Chance, because that implies an interpretation beyond the recorded event

**Embedded shot freeze frame**:
The players and locations embedded in a Shot event around that event. It is neither StatsBomb 360
nor continuous tracking data.
_Avoid_: Tracking, StatsBomb 360
