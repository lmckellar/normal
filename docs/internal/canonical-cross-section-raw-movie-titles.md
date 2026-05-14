# Canonical Cross Section of Raw Movie Titles, Edge Cases and Examples

Internal normalization corpus. These are raw pre-normalized file and folder shapes only, not a public spec and not a list of new requirements.

The set is intentionally broad: dotted scene names, folder wrappers, numeric titles, compact tokens, mixed-script prefixes, website credits, collection folders, release groups, language tags, and review-only structures all appear together so future parser changes can be checked against the full shape of the problem.

## Baseline Dotted, Spaced, and Dashed Titles

- `The.Matrix.1999.1080p.bluray.x264.aac-GRP.mkv`
- `The Matrix 1999 1080p BluRay x264 AAC-GRP.mkv`
- `The-Matrix-1999-1080p-BluRay-x264-AAC-GRP.mkv`
- `The_Matrix_1999_1080p_BluRay_x264_AAC-GRP.mkv`
- `Dune.1984.Extended.1080p.BluRay.ACE.x264-ETRG.mkv`
- `Dune 1984 Extended 1080p BluRay ACE x264-ETRG.mkv`
- `Zootopia.2016.2160p.uhd.bluray.x265-terminal.mkv`
- `Zootopia 2016 2160p UHD BluRay x265 TERMINAL.mkv`
- `A.Nightmare.on.Elm.Street.1984.Remastered.1080p.BluRay.x265.hevc.10bit.AAC.7.1.commentary-HeVK.mkv`
- `John.Wick.Chapter.2.2017..Blu-Ray.1080p.HDR.HEVC.DD.5.1-DDR.mkv`
- `Blade.Runner.2049.2017.2160p.UHD.BluRay.x265.TrueHD.7.1.Atmos-GRP.mkv`
- `The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.1080p.BluRay.x264.DTS-GRP.mkv`
- `Mad.Max.Fury.Road.2015.1080p.BluRay.x264.AC3-GRP.mkv`
- `No.Country.for.Old.Men.2007.1080p.BluRay.x264.DTS-GRP.mkv`
- `There.Will.Be.Blood.2007.1080p.BluRay.x264.DTS-GRP.mkv`
- `Eternal.Sunshine.of.the.Spotless.Mind.2004.1080p.BluRay.x264.AAC-GRP.mkv`
- `The.Grand.Budapest.Hotel.2014.1080p.BluRay.x264.AC3-GRP.mkv`
- `Everything.Everywhere.All.at.Once.2022.1080p.BluRay.x265.AAC-GRP.mkv`

## Year Placement and Numeric Title Ambiguity

- `1917.2019.1080p.Bluray.Atmos.TrueHD.7.1.x264-EVO.mkv`
- `(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO]/(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv`
- `2001 - A Space Odyssey (1968) V2 (2160p BluRay x265 HEVC 10bit HDR AAC 5.1 Tigole)/2001 - A Space Odyssey (1968) V2 (2160p BluRay x265 10bit HDR Tigole).mkv`
- `(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]/(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv`
- `1979.Mad.Max.BDRip.1080p.x264-GRP.mkv`
- `1979 Mad Max BDRip 1080p x264-GRP.mkv`
- `2010.The.Year.We.Make.Contact.1984.1080p.BluRay.x264-GRP.mkv`
- `1984.1984.1080p.BluRay.x264-GRP.mkv`
- `300.2006.1080p.BluRay.x264-GRP.mkv`
- `Se7en.1995.1080p.BluRay.x264-GRP.mkv`
- `8.1-2.1963.1080p.Criterion.BluRay.x264-GRP.mkv`
- `12.Angry.Men.1957.1080p.BluRay.x264-GRP.mkv`
- `10.Things.I.Hate.About.You.1999.1080p.BluRay.x264-GRP.mkv`
- `Three.Thousand.Years.of.Longing.2022.1080p.BluRay.x264-GRP.mkv`
- `21.Grams.2003.1080p.BluRay.x264-GRP.mkv`
- `1408.2007.Directors.Cut.1080p.BluRay.x264-GRP.mkv`
- `The.39.Steps.1935.1080p.BluRay.x264-GRP.mkv`
- `One.Cut.of.the.Dead.2017.1080p.BluRay.x264-GRP.mkv`

## Mixed-Script and Alternate-Title Prefixes

- `Коммандос.Commando.1985.Director's.Cut.BDRip-HEVC.1080p.mkv`
- `七人の侍.Seven.Samurai.1954.1080p.Criterion.BluRay.x264-GRP.mkv`
- `千と千尋の神隠し.Spirited.Away.2001.1080p.BluRay.x264-GRP.mkv`
- `卧虎藏龙.Crouching.Tiger.Hidden.Dragon.2000.1080p.BluRay.x264-GRP.mkv`
- `Cidade.de.Deus.City.of.God.2002.1080p.BluRay.x264-GRP.mkv`
- `Le.Fabuleux.Destin.d.Amelie.Poulain.Amelie.2001.1080p.BluRay.x264-GRP.mkv`
- `Der.Untergang.Downfall.2004.1080p.BluRay.x264-GRP.mkv`
- `Das.Boot.The.Boat.1981.Directors.Cut.1080p.BluRay.x264-GRP.mkv`
- `Ladri.di.Biciclette.Bicycle.Thieves.1948.1080p.BluRay.x264-GRP.mkv`
- `La.Haine.Hate.1995.1080p.BluRay.x264-GRP.mkv`
- `El.Laberinto.del.Fauno.Pans.Labyrinth.2006.1080p.BluRay.x264-GRP.mkv`
- `Fa.Yeung.Nin.Wa.In.the.Mood.for.Love.2000.1080p.BluRay.x264-GRP.mkv`
- `봄.여름.가을.겨울.그리고.봄.Spring.Summer.Fall.Winter.and.Spring.2003.1080p.BluRay.x264-GRP.mkv`
- `Андрей.Рублев.Andrei.Rublev.1966.1080p.BluRay.x264-GRP.mkv`
- `Roma.2018.SPANISH.1080p.NF.WEB-DL.DDP5.1.x264-GRP.mkv`

## Website, Uploader, and Source Credits

- `www.UIndex.org    -    Wings Of Desire 1987 1080p MAX WEB-DL DDP5 1 H 264-GPRS.mkv`
- `Www Hdsector Com Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y].mkv`
- `www.YTS.mx.The.Big.Lebowski.1998.1080p.BluRay.x264.AAC.mkv`
- `www.Torrenting.com - Heat 1995 1080p BluRay x264 DTS-GRP.mkv`
- `www.RARBG.to - Alien 1979 Directors Cut 1080p BluRay x264-GRP.mkv`
- `www.1TamilMV.foo - RRR 2022 Telugu 1080p WEB-DL DD5.1 x264-GRP.mkv`
- `[YTS.AM] Casablanca (1942) [1080p] [BluRay] [YTS.AM].mp4`
- `[TGx] The Apartment 1960 1080p BluRay x264-GRP.mkv`
- `[Erai-raws] Perfect Blue (1997) [1080p][Multiple Subtitle].mkv`
- `Downloaded.from.TorrentGalaxy.to.The.Thing.1982.1080p.BluRay.x264-GRP.mkv`
- `RARBG.COM - Robocop 1987 Directors Cut 1080p BluRay x264-GRP.mkv`
- `MoviesByRizzo - The Sting 1973 1080p BluRay x264 AAC.mkv`
- `anoXmous - The Godfather 1972 1080p BluRay x264.mp4`
- `ETRG - The Social Network 2010 720p BluRay x264.mp4`
- `HDChina - Hero 2002 1080p BluRay x264 DTS.mkv`

## Technical Token Cleanup

- `Alien.1979.Directors.Cut.1080p.BluRay.x264.DTS-GRP.mkv`
- `Aliens.1986.Special.Edition.1080p.BluRay.x264.DTS-GRP.mkv`
- `Blade.Runner.1982.Final.Cut.1080p.BluRay.x264.DTS-GRP.mkv`
- `Apocalypse.Now.1979.Final.Cut.2160p.UHD.BluRay.x265.TrueHD.7.1.Atmos-GRP.mkv`
- `The.Abyss.1989.Special.Edition.1080p.BluRay.x264.DTS-GRP.mkv`
- `Kingdom.of.Heaven.2005.Directors.Cut.1080p.BluRay.x264.DTS-GRP.mkv`
- `The.Hateful.Eight.2015.Roadshow.Version.1080p.BluRay.x264.DTS-GRP.mkv`
- `Superman.II.1980.Richard.Donner.Cut.1080p.BluRay.x264-GRP.mkv`
- `Watchmen.2009.Ultimate.Cut.1080p.BluRay.x264.DTS-GRP.mkv`
- `Leon.The.Professional.1994.International.Cut.1080p.BluRay.x264-GRP.mkv`
- `Terminator.2.Judgment.Day.1991.Skynet.Edition.1080p.BluRay.x264-GRP.mkv`
- `The.Exorcist.1973.The.Version.Youve.Never.Seen.1080p.BluRay.x264-GRP.mkv`
- `Metropolis.1927.Restored.1080p.BluRay.x264-GRP.mkv`
- `Night.of.the.Living.Dead.1968.Remastered.1080p.BluRay.x264-GRP.mkv`
- `The.Cotton.Club.1984.Encore.1080p.BluRay.x264-GRP.mkv`

## Compact Technical Tokens

- `Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv`
- `Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV]/Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV].mkv`
- `Movie.Title.2001.1080PENGITAMULTISUBX264BLURAYSHIV.mkv`
- `Movie.Title.2001.2160PBLURAYX26510BITHDRTIGOLE.mkv`
- `Movie.Title.2001.1080PWEBRIPX265AAC.mkv`
- `Movie.Title.2001.1080PWEBDLH264DDP5.1.mkv`
- `Movie.Title.2001.2160PUHDBLURAYREMUXX265HDR10TRUEHD7.1ATMOS.mkv`
- `Movie.Title.2001.720PBRRIPX264AAC.mkv`
- `Movie.Title.2001.BDRIPX264AC3.mkv`
- `Movie.Title.2001.DVDRIPXVIDMP3-GRP.avi`
- `Movie.Title.2001.H264AAC1080P-GRP.mp4`
- `Movie.Title.2001.H265HEVC10BIT-GRP.mkv`
- `Movie.Title.2001.DDP51H264-GRP.mkv`
- `Movie.Title.2001.DD51H265-GRP.mkv`
- `Movie.Title.2001.BLURAYREMUX1080PX264-GRP.mkv`
- `Movie.Title.2001.WEBDL1080PH264-GRP.mkv`
- `Movie.Title.2001.HEVC10bitHDR.AAC5.1-GRP.mkv`
- `Movie.Title.2001.1080pBluRayx264AAC-GRP.mkv`

## Release Groups and Hyphenated Suffixes

- `Dune.1984.Extended.1080p.BluRay.ACE.x264-ETRG.mkv`
- `Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-GRP.mkv`
- `The.Matrix.1999.1080p.BluRay.x264 - GRP.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-CME-v0.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-CME-v0-FINAL.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-anoXmous.mp4`
- `The.Matrix.1999.1080p.BluRay.x264-MoviesByRizzo.mp4`
- `The.Matrix.1999.1080p.BluRay.x264-Tigole.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-QxR.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-RARBG.mp4`
- `The.Matrix.1999.1080p.BluRay.x264-YIFY.mp4`
- `The.Matrix.1999.1080p.BluRay.x264-ION10.mp4`
- `The.Matrix.1999.1080p.BluRay.x264-GalaxyRG.mkv`
- `The.Matrix.1999.1080p.BluRay.x264-GPRS.mkv`

## Language Tags and Multi-Audio Naming

- `RRR.2022.TELUGU.1080p.NF.WEB-DL.DDP5.1.x264-GRP.mkv`
- `Parasite.2019.KOREAN.1080p.BluRay.x264.DTS-GRP.mkv`
- `Amelie.2001.FRENCH.1080p.BluRay.x264.DTS-GRP.mkv`
- `The.Lives.of.Others.2006.GERMAN.1080p.BluRay.x264.DTS-GRP.mkv`
- `City.of.God.2002.PORTUGUESE.1080p.BluRay.x264.DTS-GRP.mkv`
- `Crouching.Tiger.Hidden.Dragon.2000.MANDARIN.1080p.BluRay.x264.DTS-GRP.mkv`
- `The.Handmaiden.2016.KOREAN.JAPANESE.1080p.BluRay.x264.DTS-GRP.mkv`
- `Pan's.Labyrinth.2006.SPANISH.1080p.BluRay.x264.DTS-GRP.mkv`
- `Hero.2002.CHINESE.1080p.BluRay.x264.DTS-GRP.mkv`
- `Life.Is.Beautiful.1997.ITALIAN.1080p.BluRay.x264.DTS-GRP.mkv`
- `Movie.Title.2001.3Rus.Eng.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.Dual.Audio.Eng.Hin.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.MULTI.1080p.BluRay.x264.AAC-GRP.mkv`
- `Movie.Title.2001.MULTISUB.1080p.BluRay.x264.AAC-GRP.mkv`
- `Movie.Title.2001.English.Forced.Subs.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.ENG.ITA.MULTISUB.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.JPN.ENG.Dual.Audio.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.Rus.Eng.Ukr.1080p.BluRay.x264-GRP.mkv`

## Bracketed Payloads

- `(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO]/(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv`
- `(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]/(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv`
- `Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV]/Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV].mkv`
- `Movie Title (2001) [1080p BluRay x264 AAC GRP]/Movie Title (2001) [1080p BluRay x264 AAC GRP].mkv`
- `Movie Title [2001] [1080p BluRay x264 AAC GRP].mkv`
- `[2001] Movie Title [1080p BluRay x264 AAC GRP].mkv`
- `Movie Title (2001) [Director's Cut] [1080p BluRay x264 AAC GRP].mkv`
- `Movie Title (2001) [Extended] [Remastered] [1080p BluRay x264 AAC GRP].mkv`
- `Movie Title (2001) [1080p][BluRay][x264][AAC][GRP].mkv`
- `[YTS.AM] Movie Title (2001) [1080p] [BluRay] [YTS.AM].mp4`
- `[TGx] Movie Title 2001 1080p BluRay x264-GRP.mkv`
- `[Erai-raws] Movie Title (2001) [1080p][Multiple Subtitle].mkv`
- `Movie.Title.2001.[1080p.BluRay.x264.AAC-GRP].mkv`
- `Movie.Title.(2001).[1080p.BluRay.x264.AAC-GRP].mkv`
- `Movie.Title.[2001.1080p.BluRay.x264.AAC-GRP].mkv`

## Collection Wrappers and Duplicate Folder Structures

- `The.Godfather.Trilogy.[ I. II. III ].1080p.BluRay.x264.anoXmous/The.Godfather.1972.1080p.BluRay.x264.anoXmous/The.Godfather.1972.1080p.BluRay.x264.anoXmous_.mp4`
- `A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs/A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs/A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs.mkv`
- `The.Matrix.Collection.1999-2003.1080p.BluRay.x264/The.Matrix.1999.1080p.BluRay.x264-GRP/The.Matrix.1999.1080p.BluRay.x264-GRP.mkv`
- `Alien.Quadrilogy.1979-1997.1080p.BluRay.x264/Alien.1979.Directors.Cut.1080p.BluRay.x264/Alien.1979.Directors.Cut.1080p.BluRay.x264.mkv`
- `Mad.Max.Collection.1979-2015.1080p.BluRay.x264/Mad.Max.1979.1080p.BluRay.x264/Mad.Max.1979.1080p.BluRay.x264.mkv`
- `Star.Wars.Original.Trilogy.1977-1983.1080p.BluRay.x264/Star.Wars.Episode.IV.A.New.Hope.1977.1080p.BluRay.x264/Star.Wars.Episode.IV.A.New.Hope.1977.1080p.BluRay.x264.mkv`
- `The.Lord.of.the.Rings.Extended.Trilogy.2001-2003.1080p.BluRay.x264/The.Two.Towers.2002.Extended.1080p.BluRay.x264/The.Two.Towers.2002.Extended.1080p.BluRay.x264.mkv`
- `Back.to.the.Future.Trilogy.1985-1990.1080p.BluRay.x264/Back.to.the.Future.1985.1080p.BluRay.x264/Back.to.the.Future.1985.1080p.BluRay.x264.mkv`
- `Indiana.Jones.Collection.1981-2008.1080p.BluRay.x264/Raiders.of.the.Lost.Ark.1981.1080p.BluRay.x264/Raiders.of.the.Lost.Ark.1981.1080p.BluRay.x264.mkv`
- `Toy.Story.Collection.1995-2019.1080p.BluRay.x264/Toy.Story.1995.1080p.BluRay.x264/Toy.Story.1995.1080p.BluRay.x264.mkv`
- `Kill.Bill.The.Whole.Bloody.Affair.2003-2004.1080p.BluRay.x264/Kill.Bill.Volume.1.2003.1080p.BluRay.x264/Kill.Bill.Volume.1.2003.1080p.BluRay.x264.mkv`
- `Planet.of.the.Apes.Collection.1968-1973.1080p.BluRay.x264/0001.Planet.of.the.Apes.1968.1080p.BluRay.x264/0001.Planet.of.the.Apes.1968.1080p.BluRay.x264.mkv`
- `01 - The Fellowship of the Ring/The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.1080p.BluRay.x264.mkv`
- `02 - The Two Towers/The.Lord.of.the.Rings.The.Two.Towers.2002.1080p.BluRay.x264.mkv`
- `03 - The Return of the King/The.Lord.of.the.Rings.The.Return.of.the.King.2003.1080p.BluRay.x264.mkv`

## Loose Root Files

- `Dune.1984.Extended.1080p.BluRay.AC3.x264-ETRG.mkv`
- `Zootopia.2016.2160p.uhd.bluray.x265-terminal.mkv`
- `The.Matrix.1999.1080p.bluray.x264.aac-GRP.mkv`
- `Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv`
- `John.Wick.Chapter.2.2017..Blu-Ray.1080p.HDR.HEVC.DD.5.1-DDR.mkv`
- `1917.2019.1080p.Bluray.Atmos.TrueHD.7.1.x264-EVO.mkv`
- `Boundary.1999.NineChars.1080p.mkv`
- `www.UIndex.org    -    Wings Of Desire 1987 1080p MAX WEB-DL DDP5 1 H 264-GPRS.mkv`
- `Www Hdsector Com Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y].mkv`
- `A.Nightmare.on.Elm.Street.1984.Remastered.1080p.BluRay.x265.hevc.10bit.AAC.7.1.commentary-HeVK.mkv`
- `The.Big.Short.2015.1080p.BluRay.x264.DTS-GRP.mkv`
- `Moonlight.2016.1080p.BluRay.x264.AAC-GRP.mkv`
- `Get.Out.2017.1080p.BluRay.x264.AAC-GRP.mkv`
- `Arrival.2016.1080p.BluRay.x264.DTS-GRP.mkv`
- `Her.2013.1080p.BluRay.x264.AAC-GRP.mkv`

## Multi-Video Folders and Review-Only Structures

- `Movie/Feature.1999.1080p.mkv`
- `Movie/Sample.1999.1080p.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Movie.Title.2001.1080p.BluRay.x264.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Movie.Title.2001.Sample.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/CD1.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/CD2.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Part.1.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Part.2.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Behind.The.Scenes.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Interview.with.Director.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Trailer.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Featurette.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Extras/Deleted.Scenes.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Extras/Making.Of.mkv`
- `Movie.Title.2001.1080p.BluRay.x264/Extras/Short.Film.mkv`

## Missing or Weak Year Tokens

- `Movie.Title.1080p.BluRay.x264-GRP.mkv`
- `Movie Title BluRay x264 GRP.mkv`
- `Movie.Title.Directors.Cut.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.Remastered.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.Collection.1080p.BluRay.x264/Movie.Title.1080p.BluRay.x264.mkv`
- `Movie.Title.20O1.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.201.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.20010.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.1899.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2101.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.1080x1920.BluRay.x264-GRP.mkv`
- `Movie.Title.1920x820.BluRay.x264-GRP.mkv`
- `Movie.Title.3840x1600.UHD.BluRay.x265-GRP.mkv`
- `Movie.Title.1280x720.WEB-DL.x264-GRP.mkv`
- `Movie.Title.720x576.DVDRip.x264-GRP.mkv`

## Resolution and Year Collision Cases

- `Resolution.Trap.1920x820.2017.1080p.BluRay.x264-GRP.mkv`
- `Resolution.Trap.2017.1920x820.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2017.3840x2160.2160p.UHD.BluRay.x265-GRP.mkv`
- `Movie.Title.2017.1920x1080.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2017.1280x720.720p.WEB-DL.x264-GRP.mkv`
- `Movie.Title.2017.720x480.DVDRip.x264-GRP.mkv`
- `Movie.Title.2017.1916x952.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2017.1920x800.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2017.1440x1080.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2017.4K.Remux.TrueHD.Atmos-GRP.mkv`
- `Movie.Title.2017.UHD.BluRay.Remux.HEVC.HDR10-GRP.mkv`
- `Movie.Title.2017.2160p.HDR10Plus.DV.HEVC.TrueHD.Atmos-GRP.mkv`
- `Movie.Title.2017.1080p.SDR.BluRay.x264.DTS-GRP.mkv`
- `Movie.Title.2017.480p.DVDRip.x264.AAC-GRP.mkv`
- `Movie.Title.2017.576p.DVDRip.x264.AC3-GRP.mkv`

## Extension and Container Variants

- `Movie.Title.2001.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.mp4`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.m4v`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.avi`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.mov`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.wmv`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.mpg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.mpeg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.ts`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.m2ts`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.webm`
- `Movie.Title.2001.1080p.BluRay.x264-GRP`
- `Movie.Title.2001.1080p.BluRay.x264-GRP.sample.mkv`
- `._Movie.Title.2001.1080p.BluRay.x264-GRP.mkv`
- `.stash/Movie.Title.2001.1080p.BluRay.x264-GRP.mkv`

## Sidecar and Junk-Adjacent Structures

- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP.nfo`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP.srt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP.eng.srt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP.forced.srt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/poster.jpg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/folder.jpg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Movie.Title.2001.1080p.BluRay.x264-GRP-poster.jpg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/cover.png`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/fanart.jpg`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Downloaded from TorrentGalaxy.txt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/RARBG.txt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Subs/Movie.Title.2001.eng.srt`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Sample/sample.mkv`
- `Movie.Title.2001.1080p.BluRay.x264-GRP/Proof/proof.jpg`

## Article, Apostrophe, and Punctuation Cases

- `Hachi.A.Dog's.Tale.2009.BluRay.1080p.x264.AAC.5.1-HON3Y.mkv`
- `Pan's.Labyrinth.2006.SPANISH.1080p.BluRay.x264.DTS-GRP.mkv`
- `Schindler's.List.1993.1080p.BluRay.x264.DTS-GRP.mkv`
- `Singin.in.the.Rain.1952.1080p.BluRay.x264-GRP.mkv`
- `Rosemary's.Baby.1968.1080p.BluRay.x264-GRP.mkv`
- `One.Flew.Over.the.Cuckoo's.Nest.1975.1080p.BluRay.x264-GRP.mkv`
- `Who's.Afraid.of.Virginia.Woolf.1966.1080p.BluRay.x264-GRP.mkv`
- `Don't.Look.Now.1973.1080p.BluRay.x264-GRP.mkv`
- `It's.a.Wonderful.Life.1946.1080p.BluRay.x264-GRP.mkv`
- `L.A.Confidential.1997.1080p.BluRay.x264-GRP.mkv`
- `Dr.Strangelove.or.How.I.Learned.to.Stop.Worrying.and.Love.the.Bomb.1964.1080p.BluRay.x264-GRP.mkv`
- `Mr.Smith.Goes.to.Washington.1939.1080p.BluRay.x264-GRP.mkv`
- `The.Banshees.of.Inisherin.2022.1080p.BluRay.x264-GRP.mkv`
- `An.American.Werewolf.in.London.1981.1080p.BluRay.x264-GRP.mkv`
- `A.Separation.2011.PERSIAN.1080p.BluRay.x264-GRP.mkv`

## Roman Numerals, Series, and Subtitle-Like Names

- `Rocky.II.1979.1080p.BluRay.x264-GRP.mkv`
- `Rocky.III.1982.1080p.BluRay.x264-GRP.mkv`
- `Rocky.IV.1985.Directors.Cut.1080p.BluRay.x264-GRP.mkv`
- `Star.Wars.Episode.IV.A.New.Hope.1977.1080p.BluRay.x264-GRP.mkv`
- `Star.Wars.Episode.V.The.Empire.Strikes.Back.1980.1080p.BluRay.x264-GRP.mkv`
- `Star.Wars.Episode.VI.Return.of.the.Jedi.1983.1080p.BluRay.x264-GRP.mkv`
- `Mission.Impossible.III.2006.1080p.BluRay.x264-GRP.mkv`
- `Mission.Impossible.Ghost.Protocol.2011.1080p.BluRay.x264-GRP.mkv`
- `Mission.Impossible.Rogue.Nation.2015.1080p.BluRay.x264-GRP.mkv`
- `Mission.Impossible.Fallout.2018.1080p.BluRay.x264-GRP.mkv`
- `Mad.Max.2.The.Road.Warrior.1981.1080p.BluRay.x264-GRP.mkv`
- `Rambo.First.Blood.Part.II.1985.1080p.BluRay.x264-GRP.mkv`
- `Friday.the.13th.Part.VI.Jason.Lives.1986.1080p.BluRay.x264-GRP.mkv`
- `Police.Story.3.Supercop.1992.1080p.BluRay.x264-GRP.mkv`
- `The.Naked.Gun.2.1-2.The.Smell.of.Fear.1991.1080p.BluRay.x264-GRP.mkv`

## Review Pressure From Unknown Long Tokens

- `Boundary.1999.NineChars.1080p.mkv`
- `Boundary.1999.TenCharsXX.1080p.mkv`
- `Movie.Title.2001.SuperLongUnknownToken.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.PROPERREPACKREMASTERED.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.CUSTOMUPSCALEAI.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.OPENMATTEHYBRID.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.INTERNALLIMITED.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.UNRATEDEXTENDEDCUT.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.REMASTEREDCOLLECTORS.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.DIRECTORSCUTFINAL.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.UNCENSOREDFESTIVAL.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.THEATRICALRESTORE.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.SPECIALCOLLECTION.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.UNKNOWNENCODETAG.1080p.BluRay.x264-GRP.mkv`
- `Movie.Title.2001.RELEASECANDIDATE.1080p.BluRay.x264-GRP.mkv`
