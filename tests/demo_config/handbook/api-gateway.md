# API gateway

A **synthetic** demo node: nothing is probed, and the `demo` check replays its
scenario on a loop. This is what a team keeps for a node at length, read on its
*Handbook* tab, where its headings are anchored as GitHub anchors them: [Sign
in](#sign-in) leads below, and so does [When it fails](#when-it-fails).

## Sign in

Through the bastion, as yourself:

    ssh -J bastion.example.org gateway01.example.org

## When it fails

### {warn}: slow answers

Look at the upstream latency first: the gateway itself is rarely the cause.

### {error}: no answers

1. Check that the process runs: `systemctl status gateway`.
2. Restart it once: `sudo systemctl restart gateway`.
3. Still failing: page the platform team's on-call engineer.

## Who to call

| When | Whom | How |
|---|---|---|
| working hours | the platform team | its channel |
| out of hours | the on-call engineer | the number on the contact page |
| ~~weekends~~ | — | out of hours covers them |
