def averageScore(scores, weights=[]):
    total = 0
    for i in range(len(scores)):
        w = weights[i] if weights != None and i < len(weights) else 1
        total += scores[i] * w
    return total / len(scores)


def find_max(items):
    try:
        best = items[0]
        for x in items:
            if x > best:
                best = x
        return best
    except:
        return 0
