# -*- encoding: utf-8 -*-
# Copyright 2012-2015, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html

from . import tags, encoders, decoders, reduce, values, TYPES
import struct, fractions

_TAGS = tags._TAGS
_2TAG = tags._2TAG
_2KEY = tags._2KEY


class TiffTag(object):

	# IFD entries values
	tag = 0x0
	type = 0
	count = 0
	value = None

	# end user side values
	key = "Undefined"
	name = "Undefined tag"
	comment = "Nothing about this tag"
	meaning = None

	def __init__(self, tag, type=None, value=None, name="Tiff tag"):
		if tag in _2TAG: tag = _2TAG[tag]
		self.key, _typ, default, self.comment = _TAGS.get(tag, ("Unknown", [0], None, "Undefined tag 0x%x"%tag))
		self.tag = tag
		self.name = name

		self.type = _typ[-1] if type == None else type
		if value != None: self._encode(value)
		elif default != None: self.value = (default,) if not hasattr(default, "len") else default

	def __setattr__(self, attr, value):
		if attr == "type":
			try: object.__setattr__(self, "_encoder", getattr(encoders, "_%s"%hex(self.tag)))
			except AttributeError: object.__setattr__(self, "_encoder", getattr(encoders, "_%s"%value))
			try: object.__setattr__(self, "_decoder", getattr(decoders, "_%s"%hex(self.tag)))
			except AttributeError: object.__setattr__(self, "_decoder", getattr(decoders, "_%s"%value))
		elif attr == "value":
			restricted = getattr(values, self.key, None)
			if restricted != None:
				v = value[0] if isinstance(value, tuple) else value
				self.meaning = restricted.get(v, "no description found [%r]" % (v,))
			self.count = len(value) // (1 if self.type not in [5,10] else 2)
			self._determine_if_offset()
		object.__setattr__(self, attr, value)

	def __repr__(self):
		return "<%s 0x%x: %s = %r>" % (self.name, self.tag, self.key, self.value) + ("" if not self.meaning else ' := %r'%self.meaning)

	def _encode(self, value):
		self.value = self._encoder(value)

	def _decode(self):
		return self._decoder(self.value)

	def _determine_if_offset(self):
		if self.count == 1 and self.type in [1, 2, 3, 4, 6, 7, 8, 9]: setattr(self, "value_is_offset", False)
		elif self.count <= 2 and self.type in [3, 8]: setattr(self, "value_is_offset", False)
		elif self.count <= 4 and self.type in [1, 2, 6, 7]: setattr(self, "value_is_offset", False)
		else: setattr(self, "value_is_offset", True)

	def _fill(self):
		s = struct.calcsize(TYPES[self.type][0])
		voidspace = (struct.calcsize("L") - self.count*s)//s
		if self.type in [2, 7]: return self.value + b"\x00"*voidspace
		elif self.type in [1, 3, 6, 8]: return self.value + ((0,)*voidspace)
		return self.value

	def calcsize(self):
		return struct.calcsize(TYPES[self.type][0] * (self.count*(2 if self.type in [5,10] else 1))) if self.value_is_offset else 0


class Ifd(dict):
	tagname = "Tiff Tag"

	exif_ifd = property(lambda obj: obj.sub_ifd.get(34665, {}), None, None, "shortcut to EXIF sub ifd")
	gps_ifd = property(lambda obj: obj.sub_ifd.get(34853, {}), None, None, "shortcut to GPS sub ifd")
	has_raster = property(lambda obj: 273 in obj or 288 in obj or 324 in obj or 513 in obj, None, None, "return true if it contains raster data")
	raster_loaded = property(lambda obj: not(obj.has_raster) or bool(len(obj.stripes+obj.tiles+obj.free)+len(obj.jpegIF)), None, None, "")
	size = property(
		lambda obj: {
			"ifd": struct.calcsize("H" + (len(obj)*"HHLL") + "L"),
			"data": reduce(int.__add__, [t.calcsize() for t in dict.values(obj)])
		}, None, None, "return ifd-packed size and data-packed size")
		
	def __init__(self, sub_ifd={}, **kwargs):
		self._sub_ifd = sub_ifd
		setattr(self, "tagname", kwargs.pop("tagname", "Tiff tag"))
		dict.__init__(self)

		self.sub_ifd = {}
		self.stripes = ()
		self.tiles = ()
		self.free = ()
		self.jpegIF = b""

	def __setitem__(self, tag, value):
		if isinstance(tag, str): tag = _2TAG[tag]
		for t,(ts,tname) in self._sub_ifd.items():
			if tag in ts:
				if not t in self.sub_ifd:
					self.sub_ifd[t] = Ifd(sub_ifd={}, tagname=tname)
				self.sub_ifd[t].addtag(TiffTag(tag, value=value))
				return
		else:
			dict.__setitem__(self, tag, TiffTag(tag, value=value, name=self.tagname))

	def __getitem__(self, tag):
		for i in self.sub_ifd.values():
			try: return i[tag]
			except KeyError: pass
		if isinstance(tag, str): tag = _2TAG[tag]
		return dict.__getitem__(self, tag)._decode()

	def _check(self):
		for key in self.sub_ifd:
			if key not in self:
				self.addtag(TiffTag(key, 4, 0, name=self.tagname))

	def set(self, tag, typ, value):
		for t,(ts,tname) in self._sub_ifd.items():
			if tag in ts:
				if not t in self.sub_ifd:
					self.sub_ifd[t] = Ifd(sub_ifd={}, tagname=tname)
				self.sub_ifd[t].set(tag, typ, value)
				return
		tifftag = TiffTag(tag=tag, type=typ, name=self.tagname)
		tifftag.value = (value,) if not hasattr(value, "__len__") else value
		tifftag.name = self.tagname
		dict.__setitem__(self, tag, tifftag)

	def get(self, tag):
		for i in self.sub_ifd.values():
			if tag in i: return i.get(tag)
		return dict.get(self, _2TAG[tag] if isinstance(tag, str) else tag)

	def addtag(self, tifftag):
		if isinstance(tifftag, TiffTag):
			tifftag.name = self.tagname
			dict.__setitem__(self, tifftag.tag, tifftag)

	def tags(self):
		for v in sorted(dict.values(self), key=lambda e:e.tag):
			yield v
		for i in self.sub_ifd.values():
			for v in sorted(dict.values(i), key=lambda e:e.tag):
				yield v
