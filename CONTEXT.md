# Touchline Intelligence domain language

Touchline turns a pinned football event-data source into traceable research entities. These terms
name the current shot-focused domain without implying data the project does not hold.

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
A source-identified player credited with at least one stored shot. It is not a squad membership or
appearance record.
_Avoid_: Squad member, appearance

**Shot**:
One recorded source event whose event type is Shot, whether or not optional attribution or location
was recorded.
_Avoid_: Chance, because that implies an interpretation beyond the recorded event
