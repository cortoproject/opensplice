"""Parses a log generated by and looks for errors.

The parser examines a log file and decides whether it meets the
conditions given in a conditions file. If the conditions are not
satisfied, the parser raises an exception.

The conditions file is a YAML document. This document must contain a
YAML block mapping named 'parseconditions'. Nested within this mapping
can be several sub-mappings:

- desc: (optional) a description of the conditions file
- parsecontents: (required) indicates whether the contents of the log file
                  must be parsed. Values: 'yes','no'
- conditions: (required) introduces a YAML sequence which defines one
              or more conditions

A condition must contain these mappings:

- name: the identifier of the condition
- type: the type of the condition. Values: 'line'/'block'/'file'
- required: indicates if a condition is required (yes) or not allowed (no)
- inst: the number of instances which must occur.
        Can be zero, which means there must not be any instances.
        Can also be 'All', which means any number of instances are acceptable.

A 'line' condition causes the parser to try to match a single line of
log text.  If the line is matched *inst* times, then the condition is
satisifed.  The condition contains this extra mapping:

- line: a string (with possible wildcard '*') matching a line in the log file

A 'block' condition causes the parser to try to match a block of text
lines. If the block is matched *inst* times then the condition is
satisfied.  The condition contains these extra mappings:

- firstline: a string (with possible wildcard '*') matching the first line of
             the block
- lastline: a string (with possible wildcard '*') matching the last line of a
            block
- linecount: the number of lines in the block
- threshold: a crude way to discriminate between two blocks that start
             with the same *firstline*.
             If the parser finds at least *threshold* lines after *firstline*
             then it is assumed to be this block
- contiglines: used to express a 'blueprint'pdb of a text block.
             Either contiglines or firstline/lastline is expected.
- ignorelines: used to express a 'whitelist' of condition blocks.
             If a detected block condition contains one of these lines,
             then the block condition is ignored.
- pluslines: used to express fuzziness.
             Can be 'none', which means the block must be exactly as
             described by *firstline*, *lastline*, *linecount*,
             and *threshold*.
             Can also introduce a YAML sequence defining extra text which
             might be contained in the block:

  - line: a string (with possible wildcard '*') which must be matched by an
          extra line if it is present
  - maxinst: the maximum number of extra lines

A 'file' condition causes the parser to test for the presence of a
file. If the file is not present then the condition is satisfied.

"""

import logging
import math
import os
import yaml
import pdb
from example_exceptions import LogCheckFail

def checkLogs( cond, f ):

    """ Examine a log for error conditions

    Look through the log and check that it satisfies the
    conditions in the condition file. If there are errors then
    raise an exception.

    Parameters:

       cond (string): path to a conditions file

       f (filelike): a filelike thing containing the log

    Raises:

       LogCheckFail: if the log does not satisfy the conditions
    """
    #pdb.set_trace()
    # Use the conditions file to examine the log
    #
    cf = open( cond )
    doc = yaml.load( cf )
    pconds = doc["parseconditions"]
    parsecontents = pconds["parsecontents"]
    # If we need to parse the contents then read it.
    #
    logfilelines = None

    if parsecontents:
        logfilelines = f.readlines()

        logname = os.path.basename(f.name)

        # Apply the conditions to the log file.
        #
        for c in pconds["conditions"]:
            if c["type"] == 'block':
                process_block(c, logfilelines, logname)

            if c["type"] == 'line':
                process_line (c, logfilelines, logname)

            if c["type"] == 'file':
                process_file (c, logfilelines, logname)

def process_block( cond, loglines, logname ):

    """Apply a block condition to lines of text

    Parameters:

    cond (a YAML thing): a condition

    loglines (string): the contents of the log file

    Raises:

       LogCheckFail: if the block does not satisfy the condition
    """

    err_return =''
    diffcount = 0
    pluscount = 0    
    firstlinedetected = False
    maxplusinst = 0
    instcount = 0
    errorcount = 0
    firstline = ''
    lastline = ''
    contigcount = 0
    msg = ""

    condname = cond["name"]
    blockinstcount = cond["inst"]
    blocklinecount = cond["linecount"]

    iscontig = False
    if cond.get('contiglines'):
        # get block lines
        lines = split_multiline(cond["contiglines"])
        firstline = lines[0].strip()
        lastline = lines[len(lines) - 1].strip()
        iscontig = True
    else:
        # get first/last lines
        firstline = cond["firstline"]
        lastline = cond["lastline"]
        threshold = int(cond["threshold"])

        if cond["pluslines"] != "none":
            pluslines = cond["pluslines"]
        else:
            pluslines = ""


    # get 'white list'
    # if a block contains one of these lines, then it is ignored
    ignorelines = None
    if cond.get('ignorelines'):
        ignorelines = split_multiline(cond["ignorelines"])


    for line in loglines:

        # this strips leading/trailing space and newlines
        logline = line.strip()

        # look for pattern

        ignored = False
        if ignorelines:
            for s in ignorelines:
                if contains(s, logline):
                    ignored = True

        if not ignored:
            if contains(firstline, logline) and not firstlinedetected:
                blockline = ""
                fline = diffcount
                firstlinedetected = True
                pluscount = 0
                contigcount = 0
                # single plusline at present
            
        if not ignored and firstlinedetected:
            blockline = "{}\n{}".format(blockline, logline)

            if iscontig:
                # so far no pluslines for blocklines
                # check rest of lines[]
                if diffcount > fline:
                    if logline.startswith(lines[contigcount + 1]):
                        contigcount += 1
            else:
                for plusline in pluslines:
                    maxplusinst = int(plusline["maxinst"])
                    if logline == plusline["line"]:
                        pluscount += 1

        
        if not ignored and contains(lastline, logline) and firstlinedetected:
 
            firstlinedetected = False
            lline = diffcount

            diff = (lline - fline) + 1
            diffcount = 0

                # check if this text block should be ignored
                #ignored = False
                #if ignorelines:
                #for s in ignorelines:
                #    if contains(s, blockline):
                #        ignored = True

            #if not ignored:
            if iscontig:
                contigcount += 1
                if contigcount == blocklinecount:
                    instcount += 1
                    if diff > blocklinecount:
                        msg = "condition failed: exceeded Max Block Contiguous Line Count \ "
                        errorcount += 1
                    elif diff < blocklinecount:
                        msg = "condition failed: did not acquire complete block \ "
                        errorcount += 1

            else:
                if pluscount > maxplusinst: # independent of block length
                    errorcount += 1
                    msg = "condition failed: too many pluslines \ "
                else:
                    # may encounter block with same first last lines
                    # so discriminate using threshold
                    if (threshold == 0 or
                        (threshold < 0 and diff < int(math.fabs(threshold)))
                        or (threshold > 0 and
                            diff > int(math.fabs(threshold)))):
                        if diff > (blocklinecount + pluscount):
                            errorcount += 1
                            msg = "condition failed: block too large \ "
                        else:
                            # perfect or almost perfect
                            instcount += 1

        # end if logline == lastline

        diffcount += 1

    # end for line


    if (instcount != blockinstcount):
        errorcount += 1
        msg = msg + "condition failed: wrong number of blocks: expected " + str(blockinstcount) + " found " + str(instcount)

    if errorcount > 0:
        err_return = 'Block condition \"' +\
                      condname +\
                      '\" error in ' +\
                      logname +\
                      ', causes:  ' +\
                      msg +\
                      '.'

    if err_return != '' :
        #logger.info( 'condition failed: %s', cond['name'] )
        raise LogCheckFail( err_return )


    # end process_block


def process_line( cond, loglines, logname ):

    """ Apply a line condition to lines of text

    Parameters:

    cond (a YAML thing): a condition

    loglines (string): the contents of the log file

    Raises:

       LogCheckFail: if the line does not satisfy the condition
    """

    logger = logging.getLogger( 'logparser' )

    if loglines == None:
        err_return = 'Log file ' + logname + ' empty; '
        raise LogCheckFail(err_return)

    err_return =''
    instcount = 0

    condname = cond["name"]
    condline = cond["line"]
    maxinst =  cond["inst"]

    required = False
    if "required" in cond:
        required = cond["required"]

    if required:
        # condition required in log file
        for line in loglines:
            logline = line.strip()
            if contains(condline, logline):
                instcount += 1

        if maxinst != 'All':
            if instcount < int(maxinst):
                err_return += 'Too few instances in ' + logname + ': ' + condname + ' ' + str(instcount) + '; '
            elif instcount > int(maxinst):
                err_return += 'Too many instances in ' + logname + ': ' + condname + ' ' + str(instcount) + '; '

    else:
        # condition not allowed in log file
        for line in loglines:
            logline = line.strip()
            if contains(condline, logline):
                instcount +=1
                #This is to cater for situations where we allow a certain number of instances e.g. Timeouts (not always in a block)
                if instcount > maxinst:
                    err_return += 'Unexpected output in ' + logname + ': ' + condname + ' ' + logline + '; '

    if err_return != '' :
        raise LogCheckFail ( err_return )

    # end process_line


def process_file( cond, loglines, logname ):

    """Apply a file condition to lines of text

    At the moment this does not examine the file at all, and always
    raises LogCheckFail. It effectively indicates an error if the file
    exists.

    Parameters:

    cond (a YAML thing): a condition

    loglines (string): the contents of the log file

    Raises:

       LogCheckFail: if the file does not satisfy the condition

    """

    logger = logging.getLogger( 'logparser' )
    raise LogCheckFail( cond['name'] )

# Split multiline strings from yaml files
# need to be single quoted to preserve log indentation
# and avoid colon-space, quoting issues
# indenting in yaml file handled by parser lib
def split_multiline(lines):
    # multiline string remove single quotes from start/end each line
    # remove first quote
    lines = lines[1:]
    # remove intermediate quotes
    lines = lines.replace('\'\n\'','\n')
    # remove last quote
    lines = lines.replace('\'\n','')
    # make it an array
    lines = lines.split('\n')
    # strip all leading and trailing whitespaces
    lines = [s.strip() for s in lines]
    return lines


def contains(condline, logline):
    # set static function variables (to reduce need of splitting condline too often)
    if condline != contains._condline:
        # new condline relative to previous call
        contains._condline = condline
        if '*' in condline:
            # contains wild cards: split it in different search items
            contains._items = condline.split('*')
        else:
            contains._items = None

    # do the search
    found = False
    if contains._items:
        # check all items against the logline
        # this is not 'item order in line' safe, but good enough
        foundcount = 0
        for item in contains._items:
            if item in logline:
                foundcount += 1
        if foundcount == len(contains._items):
            found = True
    else:
        if condline in logline:
            found = True
    return found
# static function variables initialization
contains._condline = ""
contains._items = None