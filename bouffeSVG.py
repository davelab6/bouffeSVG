import cssutils
from cssutils import css
import xml.etree.ElementTree as ET
from svgpathtools import parse_path, Line, Arc, CubicBezier

# TODO: parse inline styles (not that I care, but)

VERBOSE = False


def verbose_print(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


class ConcatTranslat:
    # TODO: upgrade to affine

    def __init__(self):
        self._store = []

    def push(self, *args, invert=False):
        if len(args) > 1:
            clx = complex(*args)
        else:
            clx = args[0]
        if invert:
            clx = -clx
        if self._store:
            clx += self._store[-1]
        self._store.append(clx)

    def pop(self):
        try:
            del self._store[-1]
        except:
            print("uneven pop!")

    @property
    def count(self):
        return len(self._store)

    @property
    def value(self):
        try:
            return self._store[-1]
        except:
            pass
        return 0+0j


class OutMachine:

    def __init__(self):
        self._elements = []  # TODO: use string buffer
        self._hasPath = False

    @property
    def value(self):
        return ''.join(self._elements)

    def addLOC(self, txt):
        if txt[:5] == "path.":
            if not self._hasPath:
                self.beginPath()
        self._elements.append(txt + "\n")

    def addSize(self, size):
        pass  # disregard the size

    def addFill(self, color):
        self.addLOC(
            "ctx.SetBrush(wx.Brush(wx.Colour" + str(color) + "))")

    def addStroke(self, color):
        if color is None:
            self.addLOC(
                "ctx.SetPen(wx.TRANSPARENT_PEN)"
            )
        else:
            self.addLOC(
                "ctx.SetPen(wx.Pen(wx.Colour" + str(color) + "))")

    def addEllipse(self, x, y, r):
        self.addLOC(
            "path.AddEllipse" + str((x, y, r))
        )

    def beginPath(self):
        self.addLOC(
            "path = ctx.CreatePath()"
        )
        self._hasPath = True

    def moveTo(self, pt):
        self.addLOC(
            "path.MoveToPoint" + str(pt)
        )

    def lineTo(self, pt):
        self.addLOC(
            "path.AddLineToPoint" + str(pt)
        )

    def cubicTo(self, p1, p2, p3):
        self.addLOC(
            "path.AddCurveToPoint" + str(p1+p2+p3)
        )

    def quadTo(self, p1, p2, p3):
        self.addLOC(
            "path.AddQuadCurveToPoint" + str(p1+p2+p3)
        )

    def endPath(self):
        self.addLOC(
            "path.CloseSubpath()"
        )

    def fillPath(self, color):
        if color is None:
            return
        self.addStroke(None)
        self.addFill(color)
        self.addLOC(
            "ctx.DrawPath(path)"
        )


def parseTransform(text):
    f = css.CSSFunction(text)
    if len(f.seq) != 4 or f.seq[0].value != "translate(":
        print("unsupported transform: ")
        return None
    return (
        f.seq[1].value.value,
        f.seq[2].value.value
    )


def SVG2IR(filename, outMachine=None):
    def p(cmplx):
        return (
            round(cmplx.real, 3),
            round(cmplx.imag, 3)
        )

    if outMachine is None:
        outMachine = OutMachine()
    out = outMachine
    t = ConcatTranslat()

    tree = ET.parse(filename)
    root = tree.getroot()

    # viewbox will be a general offset
    ix = iy = w = h = 0
    viewbox = root.get("viewBox")
    if viewbox is not None:
        ix, iy, w, h = (float(i) for i in viewbox.split(' '))
    ##
    out.addSize((w, h))
    t.push(ix, iy, invert=True)
    ##

    # get xmlns, this is our prefix to elements in the doc
    xmlns = ''
    try:
        nsIndex = root.tag.index("}")
    except IndexError:
        verbose_print("note: no xmlns found")
    else:
        xmlns = root.tag[:nsIndex+1]

    # get the style defs
    styles = dict()
    try:
        style = root.find(xmlns + "defs").find(xmlns + "style")
    except AttributeError:
        verbose_print("note: no stylesheet processed")
    else:
        sheet = cssutils.parseString(style.text)
        for rule in sheet:
            name = rule.selectorText
            if name.startswith("."):
                name = name[1:]
            attrs = dict(rule.style)

            # attrs post processing
            fill = attrs.get("fill")
            if fill == "none":
                del attrs["fill"]
            elif fill is not None:
                v = css.ColorValue(fill)
                attrs["fill"] = (v.red, v.green, v.blue)

            styles[name] = attrs

    def parseChildren(parent):
        for child in parent.getchildren():
            # xmlns raus!!
            tag = child.tag.replace(xmlns, "")
            if tag == "defs":
                continue
            ##
            transf_ = child.get("transform")
            if transf_ is not None:
                dx, dy = parseTransform(transf_)
                t.push(dx, dy)
            ##
            fillColor = None
            try:
                attrs = styles.get(child.get("class"))
                fillColor = attrs.get("fill")
            except:
                pass
            ok = True
            if tag == "path":
                pass
            elif tag == "circle":
                out.addEllipse(
                    float(child.get("cx")) + t.value.real,
                    float(child.get("cy")) + t.value.imag,
                    float(child.get("r"))
                )
                ok = False
            elif tag == "rect":
                verbose_print("note: ignored rect")
                ok = False
            else:
                print("unknown element", tag)
                ok = False
            if ok:
                ##
                path = parse_path(child.get("d")).translated(t.value)
                closingIn = False
                movePt = None
                for seg in path:
                    if movePt is not None and p(seg.end) == p(movePt):
                        closingIn = True
                        # if the last segment is a line, just issue a close
                        # statement, else spell out the curve segment
                        if isinstance(seg, Line):
                            out.endPath()
                            continue
                    elif closingIn:
                        closingIn = False
                        movePt = None
                    if movePt is None:
                        movePt = seg.start
                        out.moveTo(p(movePt))
                    if isinstance(seg, Line):
                        out.lineTo(p(seg.end))
                    elif isinstance(seg, CubicBezier):
                        out.cubicTo(p(seg.control1), p(seg.control2), p(seg.end))
                    elif isinstance(seg, Arc):
                        #out.arcTo(p(seg.end))
                        print("ARC, unsupported!", seg.radius)
                    else:
                        print("FUUU, unsupported!", seg)
                if not closingIn:
                    out.endPath()
                ##
                out.fillPath(fillColor)
                ##
            ##
            if transf_ is not None:
                t.pop()
            ##

    # push and pop to the translate matrix as we go down the hierarchy
    groups = root.findall(xmlns + "g")
    for group in groups:
        ##
        transf = group.get("transform")
        if transf is not None:
            dx, dy = parseTransform(transf)
            t.push(dx, dy)
        ##
        parseChildren(group)
        ##
        if transf is not None:
            t.pop()
        ##
    if not groups:
        parseChildren(root)

    ##
    t.pop()
    ##

    return outMachine


if __name__ == "__main__":
    import sys
    args = sys.argv
    if len(args) < 2:
        print("gimme filename")
    else:
        out = SVG2IR(args[1])
        print(out.value)
