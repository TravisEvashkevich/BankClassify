import re
import dateutil
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from textblob.classifiers import NaiveBayesClassifier
from colorama import init, Fore, Style
from tabulate import tabulate

class BankClassify():

    def __init__(self, data="2020Data.csv"):
        """Load in the previous data (by default from 2020Data.csv) and initialise the classifier"""
        if os.path.exists(data):
            self.prev_data = pd.read_csv(data)
        else:
            self.prev_data = pd.DataFrame(columns=['date', 'desc', 'amount', 'cat'])

        self.classifier = NaiveBayesClassifier(self._get_training(self.prev_data), self._extractor)

    def add_data(self, filename, bank="nationwide"):
        """Add new data and interactively classify it.

        Arguments:
         - filename: filename of Santander-format file
        """
        if bank == "santander":
            print("adding santander data!")
            self.new_data = self._read_santander_file(filename)
        elif bank == "nationwide":
            print("adding nationwide data!")
            self.new_data = self._read_nationwide_file(filename)

        self._ask_with_guess(self.new_data)

        self.prev_data = pd.concat([self.prev_data, self.new_data], ignore_index=True)
        self._check_for_dupes()
        # sort by dates before exporting.
        self.prev_data = self.prev_data.iloc[pd.to_datetime(self.prev_data["date"], format="%d/%m/%Y").values.argsort()]
        self.prev_data.to_csv("2020Data.csv", index=False)

    def _check_for_dupes(self):
        """Go through the newly concat'd data and check for dupes
        and then ask the user if they want to keep the dupe or not
        """
        dupes = self.prev_data[self.prev_data.duplicated(keep="first")]
        dupes.reset_index(inplace=True)
        if not len(dupes) > 1:
            return

        print("Dupes found:", dupes, sep='\n')
        print("Dupes found, Y or N to keep")
        for (index, row) in reversed(list(dupes.iterrows())):
            print(index, row.values)
            decision = input("Keep?:\n")
            if decision.lower() == "n":
                self.prev_data.drop(row["index"], inplace=True)

    def _prep_for_analysis(self):
        """Prepare data for analysis in pandas, setting index types and subsetting"""
        self.prev_data = self._make_date_index(self.prev_data)

        self.prev_data['cat'] = self.prev_data['cat'].str.strip()

        self.inc = self.prev_data[self.prev_data.amount > 0]
        self.out = self.prev_data[self.prev_data.amount < 0]
        self.out.amount = self.out.amount.abs()

        self.inc_noignore = self.inc[self.inc.cat != 'Ignore']
        self.inc_noexpignore = self.inc[(self.inc.cat != 'Ignore') & (self.inc.cat != 'Expenses')]

        self.out_noignore = self.out[self.out.cat != 'Ignore']
        self.out_noexpignore = self.out[(self.out.cat != 'Ignore') & (self.out.cat != 'Expenses')]

    def _read_categories(self):
        """Read list of categories from categories.txt"""
        categories = {}

        with open('categories.txt') as f:
            for i, line in enumerate(f.readlines()):
                categories[i] = line.strip()

        return categories

    def _add_new_category(self, category):
        """Add a new category to categories.txt"""
        with open('categories.txt', 'a') as f:
            f.write('\n' + category)

    def _ask_with_guess(self, df):
        """Interactively guess categories for each transaction in df, asking each time if the guess
        is correct"""
        # Initialise colorama
        init()

        df['cat'] = ""

        categories = self._read_categories()

        for index, row in df.iterrows():

            # Generate the category numbers table from the list of categories
            cats_list = [[idnum, cat] for idnum, cat in categories.items()]
            cats_table = tabulate(cats_list)

            stripped_text = self._strip_numbers(row['desc'])

            # Guess a category using the classifier (only if there is data in the classifier)
            if len(self.classifier.train_set) > 1:
                guess = self.classifier.classify(stripped_text)
            else:
                guess = ""


            # Print list of categories
            print(chr(27) + "[2J")
            print(cats_table)
            print("\n\n")
            # Print transaction
            print("On: %s\t %.2f\n%s" % (row['date'], row['amount'], row['desc']))
            print(Fore.RED  + Style.BRIGHT + "My guess is: " + str(guess) + Fore.RESET)

            input_value = input("> ")

            if input_value.lower() == 'q':
                # If the input was 'q' then quit
                return df
            if input_value == "":
                # If the input was blank then our guess was right!
                df.at[index, 'cat'] = guess
                self.classifier.update([(stripped_text, guess)])
            else:
                # Otherwise, our guess was wrong
                try:
                    # Try converting the input to an integer category number
                    # If it works then we've entered a category
                    category_number = int(input_value)
                    category = categories[category_number]
                except ValueError:
                    # Otherwise, we've entered a new category, so add it to the list of
                    # categories
                    category = input_value
                    self._add_new_category(category)
                    categories = self._read_categories()

                # Write correct answer
                df.at[index, 'cat'] = category
                # Update classifier
                self.classifier.update([(stripped_text, category)   ])

        return df

    def _make_date_index(self, df):
        """Make the index of df a Datetime index"""
        df.index = pd.DatetimeIndex(df.date.apply(dateutil.parser.parse,dayfirst=True))

        return df

    def _read_nationwide_file(self, filename):
        """Read a file in the csv file that Nationwide provides downloads in.

        Returns a pd.DataFrame with columns of 'date', 'desc' and 'amount'."""

        with open(filename) as f:
           lines = f.readlines()


        dates = []
        descs = []
        amounts = []
        balances = []

        for line in lines[5:]:

            line = "".join(i for i in line if ord(i)<128)
            if line.strip() == '':
                continue

            splits = line.split("\",\"")
            """
            0 = Date
            1 = Transaction type
            2 = Description
            3 = Paid Out
            4 = Paid In
            5 = Balance
            """
            date = splits[0].replace("\"", "").strip()
            date = datetime.strptime(date, '%d %b %Y').strftime('%d/%m/%Y')
            dates.append(date)

            # get spend/pay in amount
            if splits[3] != "": # paid out
                spend = float(re.sub("[^0-9\.-]", "", splits[3])) * -1
            else: # paid in
                spend = float(re.sub("[^0-9\.-]", "", splits[4]))
            
            amounts.append(spend)

            #Description
            descs.append(splits[2])

            #Balance
            balance = float(re.sub("[^0-9\.-]", "", splits[5]))

            balances.append(balance)

        df = pd.DataFrame({'date':dates, 'desc':descs, 'amount':amounts, "balance":balances})

        df['amount'] = df.amount.astype(float)
        df['desc'] = df.desc.astype(str)
        df['date'] = df.date.astype(str)
        df['balance'] = df.balance.astype(float)
        return df

    def _read_santander_file(self, filename):
        """Read a file in the plain text format that Santander provides downloads in.

        Returns a pd.DataFrame with columns of 'date', 'desc' and 'amount'."""
        with open(filename, errors='replace') as f:
            lines = f.readlines()

        dates = []
        descs = []
        amounts = []

        for line in lines[4:]:

            line = "".join(i for i in line if ord(i)<128)
            if line.strip() == '':
                continue

            splitted = line.split(":")

            category = splitted[0]
            data = ":".join(splitted[1:])

            if category == 'Date':
                dates.append(data.strip())
            elif category == 'Description':
                descs.append(data.strip())
            elif category == 'Amount':
                just_numbers = re.sub("[^0-9\.-]", "", data)
                amounts.append(just_numbers.strip())

        df = pd.DataFrame({'date':dates, 'desc':descs, 'amount':amounts})

        df['amount'] = df.amount.astype(float)
        df['desc'] = df.desc.astype(str)
        df['date'] = df.date.astype(str)

        return df

    def _get_training(self, df):
        """Get training data for the classifier, consisting of tuples of
        (text, category)"""
        train = []
        subset = df[df['cat'] != '']
        for i in subset.index:
            row = subset.iloc[i]
            new_desc = self._strip_numbers(row['desc'])
            train.append( (new_desc, row['cat']) )

        return train

    def _extractor(self, doc):
        """Extract tokens from a given string"""
        # TODO: Extend to extract words within words
        # For example, MUSICROOM should give MUSIC and ROOM
        tokens = self._split_by_multiple_delims(doc, [' ', '/'])

        features = {}

        for token in tokens:
            if token == "":
                continue
            features[token] = True

        return features

    def _strip_numbers(self, s):
        """Strip numbers from the given string"""
        return re.sub("[^A-Z ]", "", s)

    def _split_by_multiple_delims(self, string, delims):
        """Split the given string by the list of delimiters given"""
        regexp = "|".join(delims)

        return re.split(regexp, string)


def main():
    bc = BankClassify()

    csvs = [str(x) for x in sorted(Path(r"./statements").iterdir(), key=os.path.getmtime, reverse=True)]
    print("Found statements:\n")
    for i, item in enumerate(csvs):
        print(f"{i}: {item}")
    csvnum = int(input("What CSV should I use?\n" ))

    bc.add_data(csvs[csvnum])

    input("Finished!")

if __name__ == "__main__":
    main()