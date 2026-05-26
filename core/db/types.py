from sqlalchemy import BigInteger, Column


def Cents(nullable: bool = False) -> Column[int]:
    return Column(BigInteger, nullable=nullable)
