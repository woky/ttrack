package bitbiz.timetracking

import java.text.DecimalFormat
import java.time._
import java.time.format.DateTimeFormatter
import scala.sys.process._
import scala.util.matching.Regex

import caseapp.ExtraName
import caseapp.core.RemainingArgs
import caseapp.core.app.CaseApp
import caseapp.core.argparser.{ArgParser, SimpleArgParser}
import org.threeten.extra.YearWeek
import scalatags.Text.all._

object HamsterUtil {

  case class Period(start: LocalDate, end: LocalDate)

  case class Config(@ExtraName("c")
                    category: Option[String],
                    @ExtraName("p")
                    period: Period,
                    @ExtraName("v")
                    vacant: Boolean = false)

  private val periodArgPattern: Regex = "^[wm](\\d\\d?)(?:-(\\d\\d))?$".r

  implicit val periodArgParser: ArgParser[Period] =
    SimpleArgParser.from[Period]("period") { s =>
      def getYear(m: Regex.Match): Int =
        Option(m.group(2)).map(_.toInt + 2000).getOrElse(Year.now().getValue)
      try periodArgPattern.findFirstMatchIn(s) match {
        case Some(m) =>
          s(0) match {
            case 'w' =>
              val week = m.group(1).toInt
              val yw = YearWeek.of(getYear(m), week)
              Right(
                Period(yw.atDay(DayOfWeek.MONDAY), yw.atDay(DayOfWeek.SUNDAY))
              )
            case 'm' =>
              val month = m.group(1).toInt
              val yw = YearMonth.of(getYear(m), month)
              Right(Period(yw.atDay(1), yw.atEndOfMonth()))
            case _ => throw new IllegalStateException()
          }
        case _ => Left(caseapp.core.Error.MalformedValue("period", s))
      } catch {
        case e: DateTimeException =>
          Left(caseapp.core.Error.MalformedValue("period", e.getMessage))
      }
    }

  def fmtDate(d: LocalDate): String = DateTimeFormatter.ISO_LOCAL_DATE.format(d)
}

import HamsterUtil._

object HamsterUtilApp extends CaseApp[Config] {

  case class DayHours(date: LocalDate, hours: Float)
  case class ReportData(days: List[DayHours])

  def generateHtmlReport(config: Config, data: ReportData): Tag = {
    val df = new DecimalFormat("#.00")
    def fmtHours(h: Float): String = df.format(h)
    val title =
      s"Working time from ${fmtDate(config.period.start)} to ${fmtDate(config.period.end)}"
    html(
      head(scalatags.Text.tags2.title(title)),
      body(
        h1(title),
        table(
          thead(th("Date"), th("Hours")),
          tbody(
            for (DayHours(date, hours) <- data.days)
              yield tr(td(fmtDate(date)), td(fmtHours(hours)))
          )
        )
      )
    )
  }

  override def run(config: Config, remainingArgs: RemainingArgs): Unit = {
    val hamsterCmd = Seq(
      "hamster",
      "export",
      "tsv",
      fmtDate(config.period.start),
      fmtDate(config.period.end)
    )
    val dayCount = config.period.start.until(config.period.end).getDays + 1
    val dayMinutes: Array[Int] = new Array(dayCount)
    hamsterCmd.lineStream.drop(1).filterNot(_.isEmpty).foreach { line =>
      val Array(_, dateTimeStr, _, minutes, category, _, _) =
        line.split("\t", -1)
      val dateStr = dateTimeStr.split(" ")(0)
      val date = LocalDate.parse(dateStr, DateTimeFormatter.ISO_LOCAL_DATE)
      val dayOffset = config.period.start.until(date).getDays
      dayMinutes(dayOffset) += minutes.toInt
    }
    val dayHours = dayMinutes.zipWithIndex.collect {
      case (minutes, index) if minutes > 0 || config.vacant =>
        DayHours(config.period.start.plusDays(index), minutes / 60f)
    }.toList
    val data = ReportData(dayHours)
    val reportHtml = generateHtmlReport(config, data)
    println(reportHtml)
  }
}
