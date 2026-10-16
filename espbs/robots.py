"""Robots groups, wildcard paths and longest-rule precedence."""
import re
from urllib.parse import urlsplit


class Robots:
    def parse(self, lines):
        self.groups = []
        agents, rules, delay = [], [], None
        started = False
        for line in [*lines, 'User-agent: __end__']:
            line = line.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            name, value = (x.strip() for x in line.split(':', 1))
            name = name.lower()
            if name == 'user-agent':
                if started:
                    self.groups.append((agents, rules, delay))
                    agents, rules, delay, started = [], [], None, False
                agents.append(value.lower())
            elif agents and name in ('allow', 'disallow'):
                started = True
                if value:
                    rules.append((value, name == 'allow'))
            elif agents and name == 'crawl-delay':
                started = True
                try:
                    delay = max(0, float(value))
                except ValueError:
                    pass

    def selected(self, agent):
        token = agent.lower().split('/')[0]
        ranked = [(max((len(a) if a != '*' else 0 for a in agents if a == '*' or a in token), default=-1), rules, delay)
                  for agents, rules, delay in self.groups]
        best = max((x[0] for x in ranked), default=-1)
        return [x for x in ranked if x[0] == best and best >= 0]

    def can_fetch(self, agent, url):
        p = urlsplit(url)
        path = p.path + ('?' + p.query if p.query else '')
        matches = []
        for _, rules, _ in self.selected(agent):
            for pattern, allow in rules:
                expression = re.escape(pattern).replace(r'\*', '.*')
                if pattern.endswith('$'):
                    expression = expression[:-2] + '$'
                if re.match(expression, path):
                    matches.append((len(pattern.replace('*', '').rstrip('$').encode()), allow))
        return max(matches)[1] if matches else True

    def crawl_delay(self, agent):
        return max((delay or 0 for _, _, delay in self.selected(agent)), default=0)
